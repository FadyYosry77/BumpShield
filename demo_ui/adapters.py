"""Typed, testable presentation adapters over the frozen BumpShield engine.

This module contains no Streamlit calls.  It translates existing core models
into small view models and exposes the two live actions used by the GUI:
deterministic migration planning and constrained repair.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from bumpshield.agent.repair_engine import RepairEngine
from bumpshield.agent.repairer import MigrationPlanningService
from bumpshield.analysis.reproducer import RegressionReproducer
from bumpshield.config import BumpShieldConfig
from bumpshield.models import (
    ApiEvidence,
    CausalDiagnosis,
    DependencyChange,
    DependencyCoordinate,
    FailureSignal,
    MigrationCandidate,
    MigrationPlan,
    MigrationPlanningResult,
    MigrationStatus,
    RepairAttempt,
    RepairResult,
    ReproductionResult,
    ReproductionStatus,
    SourceContext,
    TaskSpec,
    VerificationCheckStatus,
    VerificationStatus,
)
from bumpshield.task_io import load_task_spec, task_spec_to_dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_CASE_PATH = PROJECT_ROOT / "benchmark/cases/transitive-removed-method.json"
RESEARCH_SUMMARY_PATH = (
    PROJECT_ROOT / "benchmark/results/BUMP-FINAL-v1/summary.json"
)
RESEARCH_RESULTS_PATH = (
    PROJECT_ROOT / "benchmark/results/BUMP-FINAL-v1/results.csv"
)


@dataclass(frozen=True, slots=True)
class TaskFormValues:
    """Text fields displayed by the local task form."""

    repository: str = ""
    base_commit: str = ""
    updated_commit: str = ""
    group_id: str = ""
    artifact_id: str = ""
    old_version: str = ""
    new_version: str = ""
    state_directory: str = ""


@dataclass(frozen=True, slots=True)
class UpgradeView:
    """One dependency transition for a judge-facing card."""

    group_id: str
    artifact_id: str
    old_version: str
    new_version: str
    relationship: str


@dataclass(frozen=True, slots=True)
class FailureView:
    """Bounded source-bearing failure presentation."""

    category: str
    file: str | None
    line: int | None
    symbol: str | None
    message: str
    source_excerpt: str | None


@dataclass(frozen=True, slots=True)
class ApiChangeView:
    """Observed old/new API evidence plus unverified candidates."""

    kind: str
    class_name: str
    old_version: str | None
    new_version: str | None
    old_members: tuple[str, ...]
    new_members: tuple[str, ...]
    old_class_present: bool | None
    new_class_present: bool | None
    candidates: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiagnosisView:
    """Primary deterministic diagnosis presentation."""

    status: str
    summary: str
    evidence_strength: str | None
    evidence_score: int | None
    causal_steps: tuple[str, ...]
    explanation: str | None


@dataclass(frozen=True, slots=True)
class PlanView:
    """Bounded migration plan presentation."""

    status: str
    migration_kind: str
    affected_api: str | None
    candidates: tuple[str, ...]
    affected_files: tuple[str, ...]
    allowed_files: tuple[str, ...]
    constraints: tuple[str, ...]
    verification_requirements: tuple[str, ...]
    scope: str
    required_outcome: str
    cautious_repair: bool


@dataclass(frozen=True, slots=True)
class InvestigationView:
    """Complete judge-facing view of one existing planning result."""

    run_id: str
    artifact_directory: Path
    requested: UpgradeView
    causal: UpgradeView | None
    dependency_path: tuple[str, ...]
    failure: FailureView | None
    api_change: ApiChangeView | None
    diagnosis: DiagnosisView
    plan: PlanView
    regression_confirmed: bool
    dependency_analysis_complete: bool


@dataclass(frozen=True, slots=True)
class AttemptView:
    """One repair attempt from Git and execution ground truth."""

    number: int
    status: str
    provider_status: str | None
    files_changed: int
    lines_added: int
    lines_removed: int
    compile_status: str | None
    test_status: str | None
    verification_status: str | None
    representative_failure: str | None
    provider_issue: str | None
    patch: str


@dataclass(frozen=True, slots=True)
class VerificationView:
    """Independent verifier outcome, never provider self-report."""

    final_status: str
    verified: bool
    checks: tuple[tuple[str, str, str], ...]
    reasons: tuple[str, ...]
    attempts: tuple[AttemptView, ...]
    winning_attempt: int | None
    artifact_directory: Path


@dataclass(frozen=True, slots=True)
class ResearchStrategyView:
    """Frozen benchmark metrics for one evaluated strategy."""

    strategy: str
    verified: int
    attempted: int
    strict_vrr: float
    provider_available: int
    provider_available_vrr: float | None
    direct_verified: int
    direct_attempted: int
    transitive_verified: int
    transitive_attempted: int


@dataclass(frozen=True, slots=True)
class ResearchView:
    """Read-only committed BUMP-FINAL-v1 summary."""

    suite_id: str
    total_cases: int
    planned_trials: int
    direct_cases: int
    transitive_cases: int
    strategies: tuple[ResearchStrategyView, ...]
    dependency_correct: int
    dependency_labeled: int
    api_correct: int
    api_labeled: int
    transitive_dependency_correct: int
    transitive_dependency_labeled: int


@dataclass(frozen=True, slots=True)
class LiveInvestigationResult:
    """Existing reproduction plus planning services composed for the GUI."""

    reproduction: ReproductionResult
    planning: MigrationPlanningResult | None


class LiveBumpShieldAdapter:
    """Narrow live presentation boundary over existing BumpShield services."""

    def __init__(self, state_directory: str | Path | None = None) -> None:
        state = str(state_directory or "").strip()
        self.config = (
            BumpShieldConfig(state_root=Path(state)) if state else BumpShieldConfig()
        )

    def investigate(self, task: TaskSpec) -> LiveInvestigationResult:
        """Run existing reproduction, diagnosis, and planning services."""
        reproduction = RegressionReproducer(config=self.config).reproduce(task)
        planning = (
            MigrationPlanningService(config=self.config).plan(task)
            if reproduction.status is ReproductionStatus.CONFIRMED
            else None
        )
        return LiveInvestigationResult(reproduction, planning)

    def repair(self, task: TaskSpec) -> RepairResult:
        """Run existing constrained repair engine and independent verifier."""
        return RepairEngine(config=self.config).repair(task)


def build_task_spec(values: TaskFormValues) -> TaskSpec:
    """Construct the existing ``TaskSpec`` after basic form validation."""
    fields = {
        "repository": values.repository,
        "base commit": values.base_commit,
        "updated commit": values.updated_commit,
        "group ID": values.group_id,
        "artifact ID": values.artifact_id,
        "old version": values.old_version,
        "new version": values.new_version,
    }
    missing = [name for name, value in fields.items() if not value.strip()]
    if missing:
        raise ValueError("Missing required fields: " + ", ".join(missing))

    from bumpshield.models import DependencyUpgrade

    return TaskSpec(
        repository=Path(values.repository).expanduser().resolve(),
        base_commit=values.base_commit.strip(),
        updated_commit=values.updated_commit.strip(),
        target_dependency=DependencyUpgrade(
            group_id=values.group_id.strip(),
            artifact_id=values.artifact_id.strip(),
            old_version=values.old_version.strip(),
            new_version=values.new_version.strip(),
        ),
    )


def values_from_task(task: TaskSpec, state_directory: str = "") -> TaskFormValues:
    """Populate form values from an existing typed task."""
    target = task.target_dependency
    return TaskFormValues(
        repository=str(task.repository),
        base_commit=task.base_commit,
        updated_commit=task.updated_commit,
        group_id=target.group_id,
        artifact_id=target.artifact_id,
        old_version=target.old_version,
        new_version=target.new_version,
        state_directory=state_directory,
    )


def load_task_values(path: str | Path, state_directory: str = "") -> TaskFormValues:
    """Load a normal local task JSON through the existing task loader."""
    return values_from_task(load_task_spec(Path(path)), state_directory)


def load_demo_values(path: Path = DEMO_CASE_PATH) -> TaskFormValues:
    """Read the development-case task fields without executing the fixture."""
    resolved = path.resolve()
    data = json.loads(resolved.read_text(encoding="utf-8"))
    task = data.get("task")
    if not isinstance(task, dict) or not isinstance(task.get("target_dependency"), dict):
        raise ValueError(f"Demo case has no valid task: {resolved}")
    target = task["target_dependency"]
    repository = Path(str(task.get("repository", ""))).expanduser()
    if not repository.is_absolute():
        repository = (resolved.parent / repository).resolve()
    return TaskFormValues(
        repository=str(repository),
        base_commit=str(task.get("base_commit", "")),
        updated_commit=str(task.get("updated_commit", "")),
        group_id=str(target.get("group_id", "")),
        artifact_id=str(target.get("artifact_id", "")),
        old_version=str(target.get("old_version", "")),
        new_version=str(target.get("new_version", "")),
    )


def task_preview(task: TaskSpec) -> str:
    """Return canonical task JSON for the preview panel."""
    return json.dumps(task_spec_to_dict(task), indent=2, sort_keys=True)


def coordinate_label(coordinate: DependencyCoordinate) -> str:
    """Format one resolved Maven coordinate compactly."""
    return f"{coordinate.group_id}:{coordinate.artifact_id}:{coordinate.version}"


def dependency_path_labels(
    path: tuple[DependencyCoordinate, ...],
) -> tuple[str, ...]:
    """Format an existing dependency path without deriving a new path."""
    return tuple(coordinate_label(item) for item in path)


def source_context_text(context: SourceContext) -> str:
    """Render one bounded source context with its real focus line marked."""
    return "\n".join(
        f"{'>' if line.number == context.focus_line else ' '} {line.number:4} | {line.text}"
        for line in context.lines
    )


def failure_to_view(
    failure: FailureSignal | None,
    contexts: tuple[SourceContext, ...] = (),
) -> FailureView | None:
    """Translate one existing failure and matching source context."""
    if failure is None:
        return None
    context = next(
        (
            item
            for item in contexts
            if failure.file is not None and item.file == failure.file
        ),
        contexts[0] if contexts else None,
    )
    return FailureView(
        category=failure.category.value,
        file=str(failure.file) if failure.file is not None else None,
        line=failure.line,
        symbol=failure.symbol,
        message=failure.message,
        source_excerpt=source_context_text(context) if context is not None else None,
    )


def api_to_view(
    evidence: ApiEvidence | None,
    candidates: tuple[MigrationCandidate, ...] = (),
) -> ApiChangeView | None:
    """Translate observed API facts while preserving candidate uncertainty."""
    if evidence is None:
        return None
    old_members = evidence.old_members or evidence.old_class_members
    new_members = evidence.new_members or evidence.new_class_members
    return ApiChangeView(
        kind=evidence.kind.value,
        class_name=evidence.class_name,
        old_version=evidence.before.version if evidence.before else None,
        new_version=evidence.after.version if evidence.after else None,
        old_members=tuple(item.declaration for item in old_members),
        new_members=tuple(item.declaration for item in new_members),
        old_class_present=evidence.old_class_present,
        new_class_present=evidence.new_class_present,
        candidates=tuple(item.member.declaration for item in candidates),
    )


def diagnosis_to_view(diagnosis: CausalDiagnosis) -> DiagnosisView:
    """Translate the existing primary diagnosis without adding conclusions."""
    primary = diagnosis.primary_hypothesis
    return DiagnosisView(
        status=diagnosis.status.value,
        summary=diagnosis.summary,
        evidence_strength=(primary.evidence_strength.value if primary else None),
        evidence_score=primary.evidence_score if primary else None,
        causal_steps=(
            tuple(item.description for item in primary.causal_chain)
            if primary
            else ()
        ),
        explanation=primary.explanation if primary else None,
    )


def plan_to_view(plan: MigrationPlan) -> PlanView:
    """Translate the existing plan and exact edit boundary."""
    return PlanView(
        status=plan.status.value,
        migration_kind=plan.migration_kind.value,
        affected_api=plan.affected_member or plan.affected_class,
        candidates=tuple(item.member.declaration for item in plan.new_api_candidates),
        affected_files=tuple(str(item.file) for item in plan.affected_source_locations),
        allowed_files=tuple(str(item) for item in plan.allowed_files),
        constraints=tuple(item.value for item in plan.constraints),
        verification_requirements=tuple(
            item.value for item in plan.verification_requirements
        ),
        scope=plan.scope.value,
        required_outcome=plan.required_outcome,
        cautious_repair=plan.cautious_repair,
    )


def planning_to_view(
    result: MigrationPlanningResult,
    reproduction: ReproductionResult | None = None,
) -> InvestigationView:
    """Build one presentation view from typed Phase 6 output."""
    target = result.task.target_dependency
    target_change = next(
        (item for item in result.evidence.dependency_diff.changes if item.is_target),
        None,
    )
    requested = UpgradeView(
        group_id=target.group_id,
        artifact_id=target.artifact_id,
        old_version=target.old_version,
        new_version=target.new_version,
        relationship=(
            target_change.relationship.value if target_change else "UNKNOWN"
        ),
    )
    hypothesis = result.diagnosis.primary_hypothesis
    change = result.plan.affected_dependency
    if change is None and hypothesis and hypothesis.implicated_dependencies:
        change = hypothesis.implicated_dependencies[0]
    causal = _upgrade_view(change)
    api = _relevant_api(result)
    evidence = result.evidence
    return InvestigationView(
        run_id=result.plan.run_id,
        artifact_directory=result.plan.artifact_directory,
        requested=requested,
        causal=causal,
        dependency_path=(
            dependency_path_labels(hypothesis.dependency_path) if hypothesis else ()
        ),
        failure=failure_to_view(evidence.primary_failure, evidence.source_contexts),
        api_change=api_to_view(api, result.plan.new_api_candidates),
        diagnosis=diagnosis_to_view(result.diagnosis),
        plan=plan_to_view(result.plan),
        regression_confirmed=(
            reproduction.status is ReproductionStatus.CONFIRMED
            if reproduction is not None
            else (
                evidence.base_execution is not None
                and evidence.base_execution.status.value == "PASS"
                and evidence.updated_execution is not None
                and evidence.updated_execution.status.value == "FAIL"
            )
        ),
        dependency_analysis_complete=evidence.dependency_diff.target is not None,
    )


def attempt_to_view(attempt: RepairAttempt) -> AttemptView:
    """Translate one actual repair attempt and its Git patch."""
    patch = attempt.patch_analysis
    representative = None
    if attempt.feedback is not None:
        representative = attempt.feedback.bounded_excerpt or attempt.feedback.summary
    provider_issue = None
    if attempt.provider_result is not None and attempt.provider_result.status.value != "SUCCESS":
        provider_issue = "\n".join(
            part
            for part in (
                attempt.provider_result.summary,
                attempt.provider_result.raw_output[-2_000:],
            )
            if part.strip()
        )
    return AttemptView(
        number=attempt.attempt_number,
        status=attempt.status.value,
        provider_status=(
            attempt.provider_result.status.value if attempt.provider_result else None
        ),
        files_changed=patch.stats.files_changed if patch else len(attempt.modified_files),
        lines_added=patch.stats.lines_added if patch else attempt.lines_added,
        lines_removed=patch.stats.lines_removed if patch else attempt.lines_removed,
        compile_status=(
            attempt.compile_result.status.value if attempt.compile_result else None
        ),
        test_status=attempt.test_result.status.value if attempt.test_result else None,
        verification_status=(
            attempt.verification.status.value if attempt.verification else None
        ),
        representative_failure=representative,
        provider_issue=provider_issue,
        patch=patch.patch if patch else "",
    )


def repair_to_view(result: RepairResult) -> VerificationView:
    """Expose verification only when the independent verifier supplied it."""
    verification = result.verification
    verified = bool(
        result.status is MigrationStatus.VERIFIED_MIGRATION
        and verification is not None
        and verification.status is VerificationStatus.VERIFIED_MIGRATION
    )
    checks = (
        tuple((item.name, item.status.value, item.details) for item in verification.checks)
        if verification
        else ()
    )
    return VerificationView(
        final_status=result.status.value,
        verified=verified,
        checks=checks,
        reasons=verification.reasons if verification else (),
        attempts=tuple(attempt_to_view(item) for item in result.attempts),
        winning_attempt=result.winning_attempt,
        artifact_directory=result.artifact_directory,
    )


def status_tone(status: str) -> str:
    """Map structured statuses to restrained presentation tones."""
    if status in {
        "PASS",
        "SUCCESS",
        "SUPPORTED_DIAGNOSIS",
        "PLAN_READY",
        "VERIFIED",
        "VERIFIED_MIGRATION",
        VerificationCheckStatus.PASS.value,
    }:
        return "success"
    if status in {
        "REVIEW",
        "PARTIAL_DIAGNOSIS",
        "PLAN_PARTIAL",
        "NEEDS_HUMAN_REVIEW",
    }:
        return "review"
    if status in {"NOT_RUN", "UNAVAILABLE", "UNKNOWN"}:
        return "neutral"
    return "failure"


def friendly_error(error: Exception | str) -> tuple[str, str]:
    """Classify known failures for clear demo presentation."""
    detail = str(error)
    lowered = detail.lower()
    if "quota" in lowered or "usage limit" in lowered or "rate limit" in lowered:
        return (
            "CODING PROVIDER UNAVAILABLE",
            "BumpShield analysis remains valid, but external Codex quota is unavailable.",
        )
    if "codex" in lowered and ("not found" in lowered or "unavailable" in lowered):
        return (
            "CODING PROVIDER UNAVAILABLE",
            "Codex is unavailable. Deterministic investigation remains available.",
        )
    if "repository" in lowered or "commit" in lowered:
        return "REPOSITORY ERROR", detail
    if "base" in lowered and "fail" in lowered:
        return "BASE REVISION FAILED", detail
    if "updated" in lowered and "pass" in lowered:
        return "UPDATED REVISION PASSED", detail
    if "diagnos" in lowered or "evidence" in lowered:
        return "INVESTIGATION INCOMPLETE", detail
    return "BUMPSHIELD ERROR", detail


def load_research_results(
    path: Path = RESEARCH_SUMMARY_PATH,
    results_path: Path = RESEARCH_RESULTS_PATH,
) -> ResearchView:
    """Load committed frozen metrics read-only; never provide fallback numbers."""
    data = json.loads(path.resolve().read_text(encoding="utf-8"))
    overall = {item["strategy"]: item for item in data["overall"]}
    direct = {item["strategy"]: item for item in data["direct"]}
    transitive = {item["strategy"]: item for item in data["transitive"]}
    order = ("direct-one-shot", "direct-retry", "bumpshield")
    strategies = []
    for name in order:
        item = overall[name]
        strategies.append(
            ResearchStrategyView(
                strategy=name,
                verified=int(item["verified"]),
                attempted=int(item["attempted_valid"]),
                strict_vrr=float(item["strict_vrr"]),
                provider_available=int(item["provider_available_trials"]),
                provider_available_vrr=(
                    float(item["provider_available_vrr"])
                    if item["provider_available_vrr"] is not None
                    else None
                ),
                direct_verified=int(direct[name]["verified"]),
                direct_attempted=int(direct[name]["attempted_valid"]),
                transitive_verified=int(transitive[name]["verified"]),
                transitive_attempted=int(transitive[name]["attempted_valid"]),
            )
        )
    root = data["root_cause"]
    transitive_rows = []
    with results_path.resolve().open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["strategy"] == "bumpshield" and row["case_type"] == "TRANSITIVE":
                transitive_rows.append(row)
    transitive_labeled = sum(row["root_cause_correct"] != "" for row in transitive_rows)
    transitive_correct = sum(row["root_cause_correct"] == "True" for row in transitive_rows)
    return ResearchView(
        suite_id=str(data["suite_id"]),
        total_cases=int(data["total_cases"]),
        planned_trials=int(data["planned_trials"]),
        direct_cases=int(direct["bumpshield"]["attempted_valid"]),
        transitive_cases=int(transitive["bumpshield"]["attempted_valid"]),
        strategies=tuple(strategies),
        dependency_correct=int(root["dependency_correct"]),
        dependency_labeled=int(root["dependency_labeled"]),
        api_correct=int(root["api_correct"]),
        api_labeled=int(root["api_labeled"]),
        transitive_dependency_correct=transitive_correct,
        transitive_dependency_labeled=transitive_labeled,
    )


def list_artifacts(directory: Path) -> tuple[Path, ...]:
    """List regular run artifacts without following escaping symlinks."""
    root = directory.resolve()
    if not root.is_dir():
        return ()
    results = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        results.append(relative)
    return tuple(sorted(results, key=lambda item: item.as_posix()))


def read_artifact_text(
    directory: Path,
    relative: Path,
    max_bytes: int = 200_000,
) -> str:
    """Read one bounded text artifact contained by a run directory."""
    root = directory.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("Artifact path escapes run directory") from error
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("Artifact is not a safe regular file")
    raw = candidate.read_bytes()
    if len(raw) > max_bytes:
        raw = raw[:max_bytes]
        suffix = b"\n\n[artifact truncated by GUI]\n"
    else:
        suffix = b""
    return (raw + suffix).decode("utf-8", errors="replace")


def _upgrade_view(change: DependencyChange | None) -> UpgradeView | None:
    if change is None:
        return None
    before = change.before
    after = change.after
    coordinate = after or before
    if coordinate is None:
        return None
    return UpgradeView(
        group_id=coordinate.group_id,
        artifact_id=coordinate.artifact_id,
        old_version=before.version if before else "not resolved",
        new_version=after.version if after else "removed",
        relationship=change.relationship.value,
    )


def _relevant_api(result: MigrationPlanningResult) -> ApiEvidence | None:
    affected_class = result.plan.affected_class
    if affected_class:
        for evidence in result.evidence.api_evidence:
            if evidence.class_name == affected_class:
                return evidence
    return result.evidence.api_evidence[0] if result.evidence.api_evidence else None
