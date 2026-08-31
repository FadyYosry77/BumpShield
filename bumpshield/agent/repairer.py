"""Deterministic minimal migration planning without source modification."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from bumpshield.agent.investigator import CausalDiagnoser, DiagnosisError
from bumpshield.analysis.source_locator import SourceLocator
from bumpshield.analysis.source_usage import SourceUsageFinder
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.execution.maven import MavenExecutor
from bumpshield.models import (
    AffectedLocationKind,
    AffectedSourceLocation,
    ApiEvidence,
    ApiEvidenceKind,
    ApiMember,
    ApiMemberKind,
    CandidateMatchReason,
    CausalDiagnosis,
    CausalHypothesisKind,
    DependencyChange,
    DependencyCoordinate,
    DiagnosisRun,
    DiagnosisStatus,
    EvidenceBundle,
    EvidenceStrength,
    FailureCategory,
    FailureSignal,
    MigrationCandidate,
    MigrationCandidateKind,
    MigrationKind,
    MigrationPlan,
    MigrationPlanningResult,
    PlanScope,
    PlanStatus,
    RepairConstraint,
    RepairContext,
    RootCauseHypothesis,
    SourceContext,
    SourceFileKind,
    TaskSpec,
    VerificationCommand,
    VerificationCommandKind,
    VerificationRequirement,
    WorkspaceKind,
)
from bumpshield.repo.workspace import WorkspaceError, WorkspaceManager
from bumpshield.run import RunSetupError, require_external_path, validate_task_repository

LOGGER = logging.getLogger(__name__)
MAX_API_CANDIDATES = 5
MAX_ALLOWED_FILES = 20
MAX_REPAIR_CONTEXT_LOCATIONS = 20

# Candidate scores order lexical/type relationships only. They never represent
# replacement correctness or probability.
CANDIDATE_WEIGHTS: Mapping[str, int] = MappingProxyType({
    "SAME_MEMBER_NAME": 60,
    "SHARED_NAME_PREFIX": 30,
    "SAME_RETURN_TYPE": 15,
    "OVERLAPPING_PARAMETER_TYPE": 10,
    "SAME_DECLARING_CLASS": 5,
})
CANDIDATE_PARAMETER_DISTANCE_PENALTY = 2

BASE_REPAIR_CONSTRAINTS = (
    RepairConstraint.TARGET_VERSION_MUST_REMAIN,
    RepairConstraint.TARGET_DEPENDENCY_MUST_REMAIN,
    RepairConstraint.CAUSAL_DEPENDENCY_NO_DOWNGRADE,
    RepairConstraint.NO_TEST_DELETION,
    RepairConstraint.NO_TEST_DISABLEMENT,
    RepairConstraint.NO_TEST_SKIP_CONFIGURATION,
    RepairConstraint.NO_FUNCTIONALITY_REMOVAL,
    RepairConstraint.NO_DUMMY_IMPLEMENTATION,
    RepairConstraint.NO_COMPILER_ERROR_SUPPRESSION,
    RepairConstraint.MINIMAL_PATCH,
    RepairConstraint.NO_UNRELATED_CHANGES,
    RepairConstraint.ADDITIONAL_FILES_REQUIRE_JUSTIFICATION,
)
BASE_VERIFICATION_REQUIREMENTS = (
    VerificationRequirement.TARGET_VERSION_RETAINED,
    VerificationRequirement.TARGET_DEPENDENCY_PRESENT,
    VerificationRequirement.COMPILE_PASSES,
    VerificationRequirement.TESTS_PASS,
    VerificationRequirement.TESTS_RETAINED,
    VerificationRequirement.TESTS_ENABLED,
    VerificationRequirement.PATCH_SCOPE_ACCEPTABLE,
)
ADDITIONAL_FILE_POLICY = (
    "Initial modifications are limited to allowed_files; every additional file "
    "requires explicit evidence-backed justification."
)


class PlanningError(RuntimeError):
    """Raised when trustworthy planning orchestration cannot complete."""


class DiagnosisExecution(Protocol):
    """Phase 5 boundary consumed by standalone planning."""

    def diagnose_run(
        self, task: TaskSpec, run_id: str | None = None
    ) -> DiagnosisRun:
        """Return diagnosis and exact evidence bundle."""


class MigrationPlanner:
    """Pure transformation from diagnosis and known source usages to a plan."""

    def plan(
        self,
        evidence: EvidenceBundle,
        diagnosis: CausalDiagnosis,
        locations: tuple[AffectedSourceLocation, ...] = (),
        verification_commands: tuple[VerificationCommand, ...] = (),
    ) -> MigrationPlan:
        hypothesis = diagnosis.primary_hypothesis
        migration_kind = _migration_kind(hypothesis)
        api_evidence = _api_evidence_for(evidence, hypothesis)
        status = _planning_status(diagnosis, hypothesis, locations, api_evidence)
        candidates = (
            rank_api_candidates(api_evidence)
            if status in {PlanStatus.PLAN_READY, PlanStatus.PLAN_PARTIAL}
            and api_evidence is not None
            else ()
        )
        primary = next(
            (
                item
                for item in locations
                if item.kind is AffectedLocationKind.PRIMARY_FAILURE
            ),
            None,
        )
        allowed_files = _allowed_files(locations) if _is_actionable(status) else ()
        old_api = api_evidence.old_members if api_evidence else ()
        missing_parameters = _missing_parameter_types(
            migration_kind, old_api, candidates
        )
        affected_dependency = (
            hypothesis.implicated_dependencies[0]
            if hypothesis and hypothesis.implicated_dependencies
            else None
        )
        affected_class = api_evidence.class_name if api_evidence else None
        affected_member = (
            _normalized_symbol(api_evidence.failure_symbol)
            if api_evidence
            else None
        )
        summary = _plan_summary(
            status,
            migration_kind,
            affected_class,
            affected_member,
            len(allowed_files),
        )
        outcome = _required_outcome(
            status,
            migration_kind,
            affected_class,
            affected_member,
            affected_dependency,
            missing_parameters,
        )
        commands = verification_commands or _generic_verification_commands()
        plan_id = _plan_id(
            hypothesis,
            migration_kind,
            allowed_files,
            affected_member,
        )
        plan = MigrationPlan(
            plan_id=plan_id,
            run_id=diagnosis.run_id,
            artifact_directory=diagnosis.artifact_directory,
            status=status,
            diagnosis_status=diagnosis.status,
            hypothesis_id=hypothesis.id if hypothesis else None,
            migration_kind=migration_kind,
            summary=summary,
            target_upgrade=evidence.target_upgrade,
            affected_dependency=affected_dependency,
            affected_class=affected_class,
            affected_member=affected_member,
            old_api=old_api,
            new_api_candidates=candidates,
            missing_parameter_types=missing_parameters,
            primary_source_location=primary,
            affected_source_locations=locations,
            allowed_files=allowed_files,
            protected_files=(Path("pom.xml"),),
            required_outcome=outcome,
            constraints=BASE_REPAIR_CONSTRAINTS,
            verification_requirements=(
                BASE_VERIFICATION_REQUIREMENTS if _is_actionable(status) else ()
            ),
            verification_commands=commands if _is_actionable(status) else (),
            scope=estimate_scope(len(allowed_files)),
            cautious_repair=(
                status is PlanStatus.PLAN_PARTIAL
                or (
                    hypothesis is not None
                    and hypothesis.evidence_strength
                    not in {EvidenceStrength.VERY_STRONG, EvidenceStrength.STRONG}
                )
            ),
            additional_file_policy=ADDITIONAL_FILE_POLICY,
        )
        LOGGER.debug(
            "planned %s status=%s locations=%d allowed=%d candidates=%d scope=%s",
            migration_kind.value,
            status.value,
            len(locations),
            len(allowed_files),
            len(candidates),
            plan.scope.value,
        )
        return plan


class RepairContextBuilder:
    """Build bounded source context for a future repair agent."""

    def __init__(self, context_radius: int = 10) -> None:
        self.locator = SourceLocator(context_radius=context_radius)

    def build(
        self,
        workspace: Path | None,
        evidence: EvidenceBundle,
        diagnosis: CausalDiagnosis,
        plan: MigrationPlan,
    ) -> RepairContext:
        contexts: list[SourceContext] = []
        if workspace is not None:
            primary_failure = evidence.primary_failure
            allowed = set(plan.allowed_files)
            for location in plan.affected_source_locations:
                if location.file not in allowed:
                    continue
                if len(contexts) >= MAX_REPAIR_CONTEXT_LOCATIONS:
                    break
                signal = (
                    replace(
                        primary_failure,
                        file=location.file,
                        line=location.line,
                    )
                    if primary_failure is not None
                    else FailureSignal(
                        FailureCategory.COMPILATION_ERROR_OTHER,
                        "migration-relevant source usage",
                        file=location.file,
                        line=location.line,
                    )
                )
                context = self.locator.context_for(signal, workspace)
                if context is not None:
                    contexts.append(context)
        return RepairContext(
            run_id=plan.run_id,
            diagnosis_summary=diagnosis.summary,
            hypothesis_id=plan.hypothesis_id,
            plan=plan,
            source_contexts=tuple(contexts),
        )


class MigrationPlanningService:
    """Compose Phase 5, isolated source search, planning, and artifacts."""

    def __init__(
        self,
        diagnoser: DiagnosisExecution | None = None,
        planner: MigrationPlanner | None = None,
        usage_finder: SourceUsageFinder | None = None,
        context_builder: RepairContextBuilder | None = None,
        runner: CommandRunner | None = None,
        config: BumpShieldConfig | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.config = config or BumpShieldConfig()
        self.diagnoser = diagnoser or CausalDiagnoser(config=self.config)
        self.planner = planner or MigrationPlanner()
        self.usage_finder = usage_finder or SourceUsageFinder()
        self.context_builder = context_builder or RepairContextBuilder()

    def plan(
        self,
        task: TaskSpec,
        run_id: str | None = None,
    ) -> MigrationPlanningResult:
        try:
            diagnosis_run = self.diagnoser.diagnose_run(task, run_id=run_id)
        except DiagnosisError as error:
            raise PlanningError(str(error)) from error

        if diagnosis_run.task != task:
            raise PlanningError("diagnosis run task disagrees with planning task")
        evidence = diagnosis_run.evidence
        diagnosis = diagnosis_run.diagnosis
        if evidence.run_id is not None and evidence.run_id != diagnosis.run_id:
            raise PlanningError("evidence bundle run ID disagrees with diagnosis")
        if (
            evidence.artifact_directory is not None
            and evidence.artifact_directory.resolve()
            != diagnosis.artifact_directory.resolve()
        ):
            raise PlanningError(
                "evidence bundle artifact directory disagrees with diagnosis"
            )
        try:
            require_external_path(
                diagnosis.artifact_directory.resolve(), task.repository.resolve()
            )
        except RunSetupError as error:
            raise PlanningError(str(error)) from error
        if not diagnosis.artifact_directory.is_dir():
            raise PlanningError(
                "diagnosis artifact directory does not exist: "
                f"{diagnosis.artifact_directory}"
            )
        hypothesis = diagnosis.primary_hypothesis
        api_evidence = _api_evidence_for(evidence, hypothesis)
        locations: tuple[AffectedSourceLocation, ...] = ()
        workspace_path: Path | None = None
        commands = _generic_verification_commands()

        if (
            diagnosis.status is DiagnosisStatus.SUPPORTED_DIAGNOSIS
            and hypothesis is not None
            and api_evidence is not None
        ):
            try:
                repository, _ = validate_task_repository(task, self.runner)
                with WorkspaceManager(repository, diagnosis.run_id) as workspaces:
                    workspace = workspaces.create(
                        task.updated_commit, WorkspaceKind.UPDATED
                    )
                    workspace_path = workspace.path
                    migration_kind = _migration_kind(hypothesis)
                    locations = self.usage_finder.find(
                        workspace.path,
                        hypothesis,
                        api_evidence,
                        migration_kind,
                    )
                    commands = _workspace_verification_commands(workspace.path)
                    plan = self.planner.plan(
                        evidence,
                        diagnosis,
                        locations,
                        commands,
                    )
                    context = self.context_builder.build(
                        workspace.path,
                        evidence,
                        diagnosis,
                        plan,
                    )
            except (RunSetupError, WorkspaceError) as error:
                raise PlanningError(str(error)) from error
        else:
            plan = self.planner.plan(evidence, diagnosis, locations, commands)
            context = self.context_builder.build(
                workspace_path, evidence, diagnosis, plan
            )

        if plan.artifact_directory.resolve() != diagnosis.artifact_directory.resolve():
            raise PlanningError(
                "migration plan artifact directory disagrees with diagnosis run"
            )
        try:
            require_external_path(
                plan.artifact_directory.resolve(), task.repository.resolve()
            )
            MigrationPlanArtifacts(plan.artifact_directory).persist(plan, context)
        except (OSError, RunSetupError) as error:
            raise PlanningError(f"could not persist migration plan artifacts: {error}") from error
        return MigrationPlanningResult(task, evidence, diagnosis, plan, context)


class MigrationPlanArtifacts:
    """Append compact Phase 6 artifacts to one external diagnosis run."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def persist(self, plan: MigrationPlan, context: RepairContext) -> None:
        self._write_json("migration-plan.json", migration_plan_to_dict(plan))
        (self.path / "migration-plan.txt").write_text(
            migration_plan_report(plan), encoding="utf-8"
        )
        self._write_json("repair-context.json", repair_context_to_dict(context))

    def _write_json(self, filename: str, value: object) -> None:
        (self.path / filename).write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )


def rank_api_candidates(api_evidence: ApiEvidence) -> tuple[MigrationCandidate, ...]:
    """Rank lexical/type-related new members without selecting a replacement."""
    old_member = api_evidence.old_members[0] if api_evidence.old_members else None
    old_name = (
        old_member.name
        if old_member is not None
        else _member_name(api_evidence.failure_symbol)
    )
    if not old_name:
        return ()
    full_new_api = api_evidence.new_class_members or api_evidence.new_members
    ranked: list[tuple[int, ApiMember, tuple[CandidateMatchReason, ...]]] = []
    for member in full_new_api:
        if member.kind is not ApiMemberKind.METHOD:
            continue
        reasons = _candidate_reasons(old_name, old_member, member)
        if CandidateMatchReason.SAME_MEMBER_NAME not in reasons and (
            CandidateMatchReason.SHARED_NAME_PREFIX not in reasons
        ):
            continue
        score = _candidate_score(old_member, member, reasons)
        ranked.append((score, member, reasons))
    ranked.sort(key=lambda item: (-item[0], item[1].declaration))
    output: list[MigrationCandidate] = []
    for rank, (score, member, reasons) in enumerate(
        ranked[:MAX_API_CANDIDATES], start=1
    ):
        output.append(
            MigrationCandidate(
                rank=rank,
                class_name=api_evidence.class_name,
                member=member,
                kind=(
                    MigrationCandidateKind.SAME_NAME_NEW_SIGNATURE
                    if CandidateMatchReason.SAME_MEMBER_NAME in reasons
                    else MigrationCandidateKind.RELATED_SAME_CLASS_MEMBER
                ),
                match_reasons=reasons,
                evidence_strength=_candidate_strength(score),
            )
        )
    return tuple(output)


def estimate_scope(affected_file_count: int) -> PlanScope:
    """Classify scope solely by distinct affected-file count."""
    if affected_file_count < 0:
        raise ValueError("affected_file_count must not be negative")
    if affected_file_count <= 2:
        return PlanScope.SMALL
    if affected_file_count <= 5:
        return PlanScope.MEDIUM
    return PlanScope.LARGE


def migration_plan_to_dict(plan: MigrationPlan) -> dict[str, object]:
    """Serialize migration plan canonically."""
    return {
        "plan_id": plan.plan_id,
        "run_id": plan.run_id,
        "status": plan.status.value,
        "diagnosis_status": plan.diagnosis_status.value,
        "hypothesis_id": plan.hypothesis_id,
        "migration_kind": plan.migration_kind.value,
        "summary": plan.summary,
        "target_upgrade": {
            "group_id": plan.target_upgrade.group_id,
            "artifact_id": plan.target_upgrade.artifact_id,
            "old_version": plan.target_upgrade.old_version,
            "new_version": plan.target_upgrade.new_version,
        },
        "affected_dependency": _dependency_change_to_dict(plan.affected_dependency),
        "affected_class": plan.affected_class,
        "affected_member": plan.affected_member,
        "old_api": [_api_member_to_dict(item) for item in plan.old_api],
        "new_api_candidates": [
            _candidate_to_dict(item) for item in plan.new_api_candidates
        ],
        "missing_parameter_types": list(plan.missing_parameter_types),
        "primary_source_location": (
            _location_to_dict(plan.primary_source_location)
            if plan.primary_source_location
            else None
        ),
        "affected_source_locations": [
            _location_to_dict(item) for item in plan.affected_source_locations
        ],
        "allowed_files": [str(item) for item in plan.allowed_files],
        "protected_files": [str(item) for item in plan.protected_files],
        "required_outcome": plan.required_outcome,
        "constraints": [item.value for item in plan.constraints],
        "verification_requirements": [
            item.value for item in plan.verification_requirements
        ],
        "verification_commands": [
            {"kind": item.kind.value, "command": list(item.command)}
            for item in plan.verification_commands
        ],
        "scope": plan.scope.value,
        "cautious_repair": plan.cautious_repair,
        "additional_file_policy": plan.additional_file_policy,
    }


def repair_context_to_dict(context: RepairContext) -> dict[str, object]:
    """Serialize bounded future repair input without raw logs or full graphs."""
    return {
        "run_id": context.run_id,
        "diagnosis_summary": context.diagnosis_summary,
        "hypothesis_id": context.hypothesis_id,
        "migration_plan": migration_plan_to_dict(context.plan),
        "source_contexts": [
            {
                "file": str(item.file),
                "start_line": item.start_line,
                "end_line": item.end_line,
                "focus_line": item.focus_line,
                "lines": [
                    {"number": line.number, "text": line.text}
                    for line in item.lines
                ],
                "package": item.package,
                "imports": list(item.imports),
            }
            for item in context.source_contexts
        ],
    }


def migration_plan_report(plan: MigrationPlan) -> str:
    """Render concise deterministic planning report without patch instructions."""
    lines = [
        "BumpShield Migration Plan",
        "=========================",
        "",
        f"Run: {plan.run_id}",
        f"Plan status: {plan.status.value}",
        f"Diagnosis: {plan.diagnosis_status.value}",
        f"Migration: {plan.migration_kind.value}",
        f"Summary: {plan.summary}",
        (
            "Target upgrade: "
            f"{plan.target_upgrade.group_id}:{plan.target_upgrade.artifact_id} "
            f"{plan.target_upgrade.old_version} -> {plan.target_upgrade.new_version}"
        ),
    ]
    if plan.affected_class:
        lines.extend(["", f"Affected class: {plan.affected_class}"])
    if plan.affected_member:
        lines.append(f"Affected member: {plan.affected_member}")
    if plan.primary_source_location:
        location = plan.primary_source_location
        lines.extend(["", f"Primary: {location.file}:{location.line}"])
    related = tuple(
        item
        for item in plan.affected_source_locations
        if item.kind is not AffectedLocationKind.PRIMARY_FAILURE
    )
    if related:
        lines.extend(["", "Related locations:"])
        lines.extend(f"- {item.file}:{item.line} [{item.kind.value}]" for item in related)
    if plan.new_api_candidates:
        lines.extend(["", "New API candidates (not verified replacements):"])
        lines.extend(
            f"- {item.rank}. {item.member.declaration}"
            for item in plan.new_api_candidates
        )
    if plan.missing_parameter_types:
        lines.extend(
            ["", "New required parameter types:", *(
                f"- {item}" for item in plan.missing_parameter_types
            )]
        )
    lines.extend(["", "Required outcome:", plan.required_outcome])
    if plan.allowed_files:
        lines.extend(["", "Initial allowed files:"])
        lines.extend(f"- {item}" for item in plan.allowed_files)
    lines.extend(["", "Repair constraints:"])
    lines.extend(f"- {item.value}" for item in plan.constraints)
    if plan.verification_commands:
        lines.extend(["", "Future verification:"])
        lines.extend("- " + " ".join(item.command) for item in plan.verification_commands)
    lines.extend(["", f"Scope: {plan.scope.value}"])
    return "\n".join(lines) + "\n"


def _planning_status(
    diagnosis: CausalDiagnosis,
    hypothesis: RootCauseHypothesis | None,
    locations: tuple[AffectedSourceLocation, ...],
    api_evidence: ApiEvidence | None,
) -> PlanStatus:
    if diagnosis.status is DiagnosisStatus.AMBIGUOUS_DIAGNOSIS:
        return PlanStatus.NEEDS_HUMAN_REVIEW
    if diagnosis.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE:
        return PlanStatus.NO_ACTIONABLE_DIAGNOSIS
    if diagnosis.status is DiagnosisStatus.PARTIAL_DIAGNOSIS:
        return PlanStatus.NEEDS_HUMAN_REVIEW
    if hypothesis is None or api_evidence is None:
        return PlanStatus.NO_ACTIONABLE_DIAGNOSIS
    if any(
        item.source_kind is SourceFileKind.GENERATED_SOURCE
        and item.kind is AffectedLocationKind.PRIMARY_FAILURE
        for item in locations
    ):
        return PlanStatus.NEEDS_HUMAN_REVIEW
    if not locations or not any(
        item.kind is AffectedLocationKind.PRIMARY_FAILURE for item in locations
    ):
        return PlanStatus.PLAN_PARTIAL
    if hypothesis.evidence_strength in {
        EvidenceStrength.VERY_STRONG,
        EvidenceStrength.STRONG,
    }:
        return PlanStatus.PLAN_READY
    return PlanStatus.PLAN_PARTIAL


def _migration_kind(hypothesis: RootCauseHypothesis | None) -> MigrationKind:
    if hypothesis is None:
        return MigrationKind.UNKNOWN
    return {
        CausalHypothesisKind.REMOVED_MEMBER: MigrationKind.REMOVED_METHOD,
        CausalHypothesisKind.CHANGED_MEMBER_SIGNATURE:
            MigrationKind.CHANGED_METHOD_SIGNATURE,
        CausalHypothesisKind.REMOVED_CLASS: MigrationKind.REMOVED_CLASS,
        CausalHypothesisKind.REMOVED_PACKAGE: MigrationKind.REMOVED_PACKAGE,
        CausalHypothesisKind.REMOVED_DEPENDENCY: MigrationKind.REMOVED_DEPENDENCY,
    }.get(hypothesis.kind, MigrationKind.UNKNOWN)


def _api_evidence_for(
    evidence: EvidenceBundle,
    hypothesis: RootCauseHypothesis | None,
) -> ApiEvidence | None:
    if hypothesis is None:
        return None
    expected_kind = {
        CausalHypothesisKind.REMOVED_MEMBER: ApiEvidenceKind.REMOVED_MEMBER,
        CausalHypothesisKind.CHANGED_MEMBER_SIGNATURE:
            ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE,
        CausalHypothesisKind.REMOVED_CLASS: ApiEvidenceKind.REMOVED_CLASS,
        CausalHypothesisKind.REMOVED_PACKAGE: ApiEvidenceKind.PACKAGE_REMOVED,
        CausalHypothesisKind.REMOVED_DEPENDENCY:
            ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS,
    }.get(hypothesis.kind)
    if expected_kind is None:
        return None
    changes = set(hypothesis.implicated_dependencies)
    candidates = [
        item
        for item in evidence.api_evidence
        if item.kind is expected_kind
        and any(
            item.before == change.before and item.after == change.after
            for change in changes
        )
        and (
            hypothesis.failure is None
            or item.failure_symbol == hypothesis.failure.symbol
        )
    ]
    return sorted(candidates, key=lambda item: item.class_name)[0] if candidates else None


def _candidate_reasons(
    old_name: str,
    old_member: ApiMember | None,
    candidate: ApiMember,
) -> tuple[CandidateMatchReason, ...]:
    reasons = [CandidateMatchReason.SAME_DECLARING_CLASS]
    if candidate.name == old_name:
        reasons.append(CandidateMatchReason.SAME_MEMBER_NAME)
    elif _shared_prefix_length(candidate.name, old_name) >= 4:
        reasons.append(CandidateMatchReason.SHARED_NAME_PREFIX)
    if old_member and candidate.return_type == old_member.return_type:
        reasons.append(CandidateMatchReason.SAME_RETURN_TYPE)
    if old_member and set(candidate.parameter_types) & set(old_member.parameter_types):
        reasons.append(CandidateMatchReason.OVERLAPPING_PARAMETER_TYPES)
    return tuple(reasons)


def _candidate_score(
    old_member: ApiMember | None,
    candidate: ApiMember,
    reasons: tuple[CandidateMatchReason, ...],
) -> int:
    score = CANDIDATE_WEIGHTS["SAME_DECLARING_CLASS"]
    if CandidateMatchReason.SAME_MEMBER_NAME in reasons:
        score += CANDIDATE_WEIGHTS["SAME_MEMBER_NAME"]
    if CandidateMatchReason.SHARED_NAME_PREFIX in reasons:
        score += CANDIDATE_WEIGHTS["SHARED_NAME_PREFIX"]
    if CandidateMatchReason.SAME_RETURN_TYPE in reasons:
        score += CANDIDATE_WEIGHTS["SAME_RETURN_TYPE"]
    if CandidateMatchReason.OVERLAPPING_PARAMETER_TYPES in reasons:
        overlap = len(
            set(candidate.parameter_types)
            & set(old_member.parameter_types if old_member else ())
        )
        score += min(2, overlap) * CANDIDATE_WEIGHTS["OVERLAPPING_PARAMETER_TYPE"]
    if old_member:
        score -= (
            abs(len(candidate.parameter_types) - len(old_member.parameter_types))
            * CANDIDATE_PARAMETER_DISTANCE_PENALTY
        )
    return score


def _candidate_strength(score: int) -> EvidenceStrength:
    if score >= 80:
        return EvidenceStrength.STRONG
    if score >= 45:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


def _missing_parameter_types(
    migration_kind: MigrationKind,
    old_api: tuple[ApiMember, ...],
    candidates: tuple[MigrationCandidate, ...],
) -> tuple[str, ...]:
    if migration_kind is not MigrationKind.CHANGED_METHOD_SIGNATURE:
        return ()
    if not old_api or not candidates:
        return ()
    candidate = candidates[0]
    if candidate.kind is not MigrationCandidateKind.SAME_NAME_NEW_SIGNATURE:
        return ()
    old_parameters = old_api[0].parameter_types
    new_parameters = candidate.member.parameter_types
    if new_parameters[: len(old_parameters)] != old_parameters:
        return ()
    return new_parameters[len(old_parameters) :]


def _allowed_files(
    locations: tuple[AffectedSourceLocation, ...],
) -> tuple[Path, ...]:
    priority = {
        AffectedLocationKind.PRIMARY_FAILURE: 0,
        AffectedLocationKind.EXACT_IMPORT: 1,
        AffectedLocationKind.POTENTIAL_CALL_SITE: 2,
        AffectedLocationKind.POTENTIAL_TYPE_REFERENCE: 3,
    }
    file_priorities: dict[Path, int] = {}
    for item in locations:
        if item.source_kind not in {
            SourceFileKind.PRODUCTION_SOURCE,
            SourceFileKind.TEST_SOURCE,
        }:
            continue
        file_priorities[item.file] = min(
            file_priorities.get(item.file, len(priority)),
            priority[item.kind],
        )
    ordered = sorted(file_priorities, key=lambda path: (file_priorities[path], str(path)))
    return tuple(ordered[:MAX_ALLOWED_FILES])


def _plan_summary(
    status: PlanStatus,
    migration_kind: MigrationKind,
    class_name: str | None,
    member: str | None,
    file_count: int,
) -> str:
    if not _is_actionable(status):
        return "No automatic migration plan is actionable from the diagnosis."
    subject = ".".join(item for item in (class_name, member) if item)
    return (
        f"Plan {migration_kind.value} migration for {subject or 'diagnosed API'} "
        f"across {file_count} bounded source file(s)."
    )


def _required_outcome(
    status: PlanStatus,
    migration_kind: MigrationKind,
    class_name: str | None,
    member: str | None,
    dependency: DependencyChange | None,
    missing_parameters: tuple[str, ...],
) -> str:
    if not _is_actionable(status):
        return "Collect human-reviewed evidence before changing project source."
    api = ".".join(item for item in (class_name, member) if item) or "diagnosed API"
    coordinate = dependency.after if dependency else None
    compatible = (
        f" while remaining compatible with {coordinate.group_id}:"
        f"{coordinate.artifact_id}:{coordinate.version}"
        if coordinate
        else " while preserving the upgraded dependency resolution"
    )
    if migration_kind is MigrationKind.REMOVED_METHOD:
        return f"Project source must stop relying on removed {api}{compatible}."
    if migration_kind is MigrationKind.CHANGED_METHOD_SIGNATURE:
        requirement = (
            " New argument types required by observed signature: "
            + ", ".join(missing_parameters)
            + ". No argument values are selected by this plan."
            if missing_parameters
            else " Calls must satisfy an observed new signature without invented values."
        )
        return f"Project calls to {api} must match the upgraded API{compatible}.{requirement}"
    if migration_kind is MigrationKind.REMOVED_CLASS:
        return f"Project source must stop relying on unavailable class {class_name}{compatible}."
    if migration_kind is MigrationKind.REMOVED_PACKAGE:
        return (
            "Project imports must stop relying on unavailable package "
            f"{class_name}{compatible}."
        )
    if migration_kind is MigrationKind.REMOVED_DEPENDENCY:
        return (
            "Project source must stop relying on APIs supplied only by the removed "
            f"dependency{compatible}."
        )
    return "Project source must be adapted to the supported diagnosis without unrelated changes."


def _plan_id(
    hypothesis: RootCauseHypothesis | None,
    migration_kind: MigrationKind,
    allowed_files: tuple[Path, ...],
    member: str | None,
) -> str:
    identity = "|".join(
        (
            hypothesis.id if hypothesis else "none",
            migration_kind.value,
            member or "none",
            *(str(item) for item in allowed_files),
        )
    )
    return "P-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10].upper()


def _generic_verification_commands() -> tuple[VerificationCommand, ...]:
    return (
        VerificationCommand(
            VerificationCommandKind.FAST_CHECK, ("mvn", "-B", "compile")
        ),
        VerificationCommand(
            VerificationCommandKind.FINAL_CHECK, ("mvn", "-B", "test")
        ),
    )


def _workspace_verification_commands(
    workspace: Path,
) -> tuple[VerificationCommand, ...]:
    return (
        VerificationCommand(
            VerificationCommandKind.FAST_CHECK,
            MavenExecutor.lifecycle_command_for(workspace, "compile"),
        ),
        VerificationCommand(
            VerificationCommandKind.FINAL_CHECK,
            MavenExecutor.lifecycle_command_for(workspace, "test"),
        ),
    )


def _is_actionable(status: PlanStatus) -> bool:
    return status in {PlanStatus.PLAN_READY, PlanStatus.PLAN_PARTIAL}


def _normalized_symbol(symbol: str | None) -> str | None:
    if not symbol:
        return None
    return re.sub(r"^(?:method|class|variable)\s+", "", symbol).strip()


def _member_name(symbol: str | None) -> str | None:
    normalized = _normalized_symbol(symbol)
    if not normalized:
        return None
    return normalized.split("(", 1)[0].rsplit(".", 1)[-1]


def _shared_prefix_length(left: str, right: str) -> int:
    length = 0
    for left_character, right_character in zip(left.lower(), right.lower()):
        if left_character != right_character:
            break
        length += 1
    return length


def _location_to_dict(location: AffectedSourceLocation) -> dict[str, object]:
    return {
        "file": str(location.file),
        "line": location.line,
        "kind": location.kind.value,
        "source_kind": location.source_kind.value,
        "evidence_strength": location.evidence_strength.value,
        "excerpt": location.excerpt,
    }


def _api_member_to_dict(member: ApiMember) -> dict[str, object]:
    return {
        "kind": member.kind.value,
        "name": member.name,
        "declaration": member.declaration,
        "parameter_types": list(member.parameter_types),
        "return_type": member.return_type,
        "static": member.is_static,
    }


def _candidate_to_dict(candidate: MigrationCandidate) -> dict[str, object]:
    return {
        "rank": candidate.rank,
        "class": candidate.class_name,
        "member": _api_member_to_dict(candidate.member),
        "kind": candidate.kind.value,
        "match_reasons": [item.value for item in candidate.match_reasons],
        "evidence_strength": candidate.evidence_strength.value,
        "verified_replacement": candidate.verified_replacement,
    }


def _dependency_change_to_dict(change: DependencyChange | None) -> object:
    if change is None:
        return None

    def coordinate(value: DependencyCoordinate | None) -> object:
        if value is None:
            return None
        return {
            "group_id": value.group_id,
            "artifact_id": value.artifact_id,
            "version": value.version,
            "type": value.type,
            "classifier": value.classifier,
        }

    return {
        "kind": change.kind.value,
        "relationship": change.relationship.value,
        "is_target": change.is_target,
        "before": coordinate(change.before),
        "after": coordinate(change.after),
    }
