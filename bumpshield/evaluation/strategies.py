"""Fair evaluation adapters around the existing repair and verifier pipeline."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from bumpshield.agent.repair_engine import RepairEngine, RepairPlanning
from bumpshield.agent.repairer import MigrationPlanningService
from bumpshield.analysis.failure_parser import FailureAnalyzer
from bumpshield.config import BumpShieldConfig
from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkValidationStatus,
    EvaluationFinalStatus,
    FailureReason,
    StrategyId,
)
from bumpshield.evaluation.failures import failure_domain, repair_provider_failure
from bumpshield.models import (
    AffectedLocationKind,
    AffectedSourceLocation,
    CausalDiagnosis,
    DiagnosisStatus,
    EvidenceBundle,
    EvidenceStrength,
    MigrationKind,
    MigrationPlan,
    MigrationPlanningResult,
    MigrationStatus,
    PatchScopeStatus,
    PlanScope,
    PlanStatus,
    RepairConstraint,
    RepairContext,
    RepairResult,
    SourceFileKind,
    TaskSpec,
    VerificationCommand,
    VerificationCommandKind,
    VerificationRequirement,
)


class StrategyExecutionError(RuntimeError):
    """Raised when a strategy cannot produce a trustworthy structured result."""


class EvaluationStrategy(Protocol):
    """One bounded repair strategy evaluated by the benchmark runner."""

    id: StrategyId
    maximum_provider_calls: int

    def run(
        self,
        case: BenchmarkCase,
        benchmark_run_id: str,
        trial: int,
    ) -> BenchmarkCaseResult:
        """Run one fresh case/strategy trial."""
        ...


class BumpShieldStrategy:
    """Use the complete existing diagnosis, plan, repair, and verifier pipeline."""

    id = StrategyId.BUMPSHIELD

    def __init__(
        self,
        config: BumpShieldConfig,
        engine_factory: Callable[[RepairPlanning], RepairEngine] | None = None,
    ) -> None:
        self.config = config
        self.maximum_provider_calls = config.max_repair_attempts
        self.engine_factory = engine_factory or (
            lambda planning: RepairEngine(planning=planning, config=config)
        )

    def run(
        self,
        case: BenchmarkCase,
        benchmark_run_id: str,
        trial: int,
    ) -> BenchmarkCaseResult:
        planning = TimedPlanning(MigrationPlanningService(config=self.config))
        result = self.engine_factory(planning).repair(case.task)
        return result_from_repair(
            benchmark_run_id,
            case,
            self.id,
            trial,
            result,
            diagnosis_duration_seconds=planning.duration_seconds,
        )


class TimedPlanning:
    """Measure the existing deterministic planning service without changing it."""

    def __init__(self, delegate: RepairPlanning) -> None:
        self.delegate = delegate
        self.duration_seconds: float | None = None

    def plan(
        self, task: TaskSpec, run_id: str | None = None
    ) -> MigrationPlanningResult:
        started = time.monotonic()
        try:
            return self.delegate.plan(task, run_id=run_id)
        finally:
            self.duration_seconds = time.monotonic() - started


class DirectOneShotStrategy:
    """One provider call with failure context but no causal or API evidence."""

    id = StrategyId.DIRECT_ONE_SHOT
    maximum_provider_calls = 1

    def __init__(
        self,
        config: BumpShieldConfig,
        engine_factory: Callable[[DirectBaselinePlanning, BumpShieldConfig], RepairEngine]
        | None = None,
    ) -> None:
        self.config = replace(config, max_repair_attempts=1)
        self.engine_factory = engine_factory or (
            lambda planning, effective: RepairEngine(
                planning=planning, config=effective
            )
        )

    def run(
        self,
        case: BenchmarkCase,
        benchmark_run_id: str,
        trial: int,
    ) -> BenchmarkCaseResult:
        planning = DirectBaselinePlanning(
            config=self.config, strategy_id=self.id
        )
        result = self.engine_factory(planning, self.config).repair(case.task)
        return result_from_repair(
            benchmark_run_id, case, self.id, trial, result
        )


class DirectRetryStrategy:
    """Matched retry baseline: execution feedback, never causal evidence."""

    id = StrategyId.DIRECT_RETRY

    def __init__(
        self,
        config: BumpShieldConfig,
        engine_factory: Callable[[DirectBaselinePlanning, BumpShieldConfig], RepairEngine]
        | None = None,
    ) -> None:
        self.config = config
        self.maximum_provider_calls = config.max_repair_attempts
        self.engine_factory = engine_factory or (
            lambda planning, effective: RepairEngine(
                planning=planning, config=effective
            )
        )

    def run(
        self,
        case: BenchmarkCase,
        benchmark_run_id: str,
        trial: int,
    ) -> BenchmarkCaseResult:
        planning = DirectBaselinePlanning(
            config=self.config, strategy_id=self.id
        )
        result = self.engine_factory(planning, self.config).repair(case.task)
        return result_from_repair(
            benchmark_run_id, case, self.id, trial, result
        )


class DirectBaselinePlanning:
    """Compatibility adapter exposing only bounded updated-build failure evidence."""

    def __init__(
        self,
        config: BumpShieldConfig,
        failure_analyzer: FailureAnalyzer | None = None,
        strategy_id: StrategyId = StrategyId.DIRECT_ONE_SHOT,
    ) -> None:
        self.config = config
        self.strategy_id = strategy_id
        self.failure_analyzer = failure_analyzer or FailureAnalyzer(config=config)

    def plan(
        self,
        task: TaskSpec,
        run_id: str | None = None,
    ) -> MigrationPlanningResult:
        """Build neutral engine input without dependency diff, javap, or diagnosis."""
        failure = self.failure_analyzer.analyze(task, run_id=run_id)
        primary = failure.primary_failure
        localized = primary is not None and primary.file is not None and primary.line
        status = PlanStatus.PLAN_READY if localized else PlanStatus.NO_ACTIONABLE_DIAGNOSIS
        source = next(
            (
                context
                for context in failure.source_contexts
                if primary is not None
                and context.file == primary.file
                and context.focus_line == primary.line
            ),
            None,
        )
        location = (
            AffectedSourceLocation(
                file=primary.file,
                line=primary.line,
                kind=AffectedLocationKind.PRIMARY_FAILURE,
                source_kind=_source_kind(primary.file),
                evidence_strength=EvidenceStrength.STRONG,
                excerpt=(
                    "\n".join(line.text for line in source.lines)
                    if source is not None
                    else primary.message
                ),
            )
            if localized
            else None
        )
        observed = (
            f"{primary.category.value}: {primary.message}"
            if primary is not None
            else "updated Maven build failed without a localized primary diagnostic"
        )
        plan_id = hashlib.sha256(
            f"{self.strategy_id.value}\0{task.updated_commit}\0{observed}".encode()
        ).hexdigest()[:20]
        constraints = (
            RepairConstraint.TARGET_VERSION_MUST_REMAIN,
            RepairConstraint.TARGET_DEPENDENCY_MUST_REMAIN,
            RepairConstraint.NO_TEST_DELETION,
            RepairConstraint.NO_TEST_DISABLEMENT,
            RepairConstraint.NO_TEST_SKIP_CONFIGURATION,
            RepairConstraint.NO_FUNCTIONALITY_REMOVAL,
            RepairConstraint.NO_DUMMY_IMPLEMENTATION,
            RepairConstraint.NO_COMPILER_ERROR_SUPPRESSION,
            RepairConstraint.MINIMAL_PATCH,
            RepairConstraint.NO_UNRELATED_CHANGES,
        )
        commands = (
            VerificationCommand(
                VerificationCommandKind.FAST_CHECK, ("mvn", "-B", "compile")
            ),
            VerificationCommand(
                VerificationCommandKind.FINAL_CHECK, ("mvn", "-B", "test")
            ),
        )
        plan = MigrationPlan(
            plan_id=plan_id,
            run_id=failure.run_id,
            artifact_directory=failure.artifact_directory,
            status=status,
            diagnosis_status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
            hypothesis_id=None,
            migration_kind=MigrationKind.UNKNOWN,
            summary="Direct repair baseline with no causal-analysis input.",
            target_upgrade=task.target_dependency,
            affected_dependency=None,
            affected_class=None,
            affected_member=None,
            old_api=(),
            new_api_candidates=(),
            missing_parameter_types=(),
            primary_source_location=location,
            affected_source_locations=(location,) if location else (),
            allowed_files=(location.file,) if location else (),
            protected_files=(Path("pom.xml"),),
            required_outcome=(
                f"Repair the observed Maven failure ({observed}) while retaining "
                f"{task.target_dependency.group_id}:"
                f"{task.target_dependency.artifact_id}:"
                f"{task.target_dependency.new_version}."
            ),
            constraints=constraints,
            verification_requirements=(
                VerificationRequirement.TARGET_VERSION_RETAINED,
                VerificationRequirement.TARGET_DEPENDENCY_PRESENT,
                VerificationRequirement.COMPILE_PASSES,
                VerificationRequirement.TESTS_PASS,
                VerificationRequirement.TESTS_RETAINED,
                VerificationRequirement.TESTS_ENABLED,
                VerificationRequirement.PATCH_SCOPE_ACCEPTABLE,
            ),
            verification_commands=commands,
            scope=PlanScope.SMALL,
            cautious_repair=True,
            additional_file_policy=(
                "Small source expansion requires direct relevance to the observed failure."
            ),
        )
        summary = (
            "Observed updated-build failure only; no dependency diff, API evidence, "
            "causal dependency, or migration recommendation was supplied."
        )
        diagnosis = CausalDiagnosis(
            run_id=failure.run_id,
            status=DiagnosisStatus.INSUFFICIENT_EVIDENCE,
            artifact_directory=failure.artifact_directory,
            hypotheses=(),
            summary=summary,
        )
        evidence = EvidenceBundle(
            target_upgrade=task.target_dependency,
            run_id=failure.run_id,
            task=task,
            artifact_directory=failure.artifact_directory,
            updated_execution=failure.execution,
            failures=(primary,) if primary is not None else (),
            source_contexts=(source,) if source is not None else (),
        )
        context = RepairContext(
            run_id=failure.run_id,
            diagnosis_summary=summary,
            hypothesis_id=None,
            plan=plan,
            source_contexts=(source,) if source is not None else (),
        )
        return MigrationPlanningResult(task, evidence, diagnosis, plan, context)


def result_from_repair(
    benchmark_run_id: str,
    case: BenchmarkCase,
    strategy: StrategyId,
    trial: int,
    result: RepairResult,
    *,
    diagnosis_duration_seconds: float | None = None,
) -> BenchmarkCaseResult:
    """Extract comparable metrics from Git/Maven-grounded RepairResult data."""
    representative = (
        next(
            (
                attempt
                for attempt in result.attempts
                if attempt.attempt_number == result.winning_attempt
            ),
            None,
        )
        if result.winning_attempt is not None
        else result.attempts[-1] if result.attempts else None
    )
    hypothesis = result.report.hypothesis if result.report else None
    diagnosed = None
    if hypothesis and hypothesis.implicated_dependencies:
        change = hypothesis.implicated_dependencies[0]
        coordinate = change.after or change.before
        if coordinate is not None:
            diagnosed = f"{coordinate.group_id}:{coordinate.artifact_id}"
    truth = case.ground_truth
    root_correct = None
    api_correct = None
    if strategy is StrategyId.BUMPSHIELD and truth is not None:
        expected = truth.breaking_dependency
        root_correct = bool(
            hypothesis
            and any(
                (change.after or change.before) is not None
                and (change.after or change.before).group_id == expected.group_id
                and (change.after or change.before).artifact_id == expected.artifact_id
                for change in hypothesis.implicated_dependencies
            )
        )
        api_correct = _api_ground_truth_matches(hypothesis, truth)
    final = EvaluationFinalStatus(result.status.value)
    reason = _failure_reason(result)
    provider_failure = repair_provider_failure(result)
    return BenchmarkCaseResult(
        benchmark_run_id=benchmark_run_id,
        case_id=case.id,
        case_type=case.case_type,
        case_source=case.source,
        failure_kind=truth.failure_kind if truth else None,
        strategy=strategy,
        trial=trial,
        validation_status=BenchmarkValidationStatus.VALID,
        final_status=final,
        verified=result.status is MigrationStatus.VERIFIED_MIGRATION,
        root_cause_correct=root_correct,
        api_change_correct=api_correct,
        diagnosis_status=(
            _diagnosis_status(result.report.hypothesis.status.value)
            if strategy is StrategyId.BUMPSHIELD
            and result.report
            and result.report.hypothesis
            else None
        ),
        diagnosis_strength=(
            result.report.hypothesis.evidence_strength.value
            if result.report and result.report.hypothesis
            else None
        ),
        diagnosis_score=(
            result.report.hypothesis.evidence_score
            if result.report and result.report.hypothesis
            else None
        ),
        plan_status=(
            PlanStatus.PLAN_READY.value if result.attempts else None
        ),
        diagnosed_dependency=diagnosed,
        attempt_count=len(result.attempts),
        provider_calls=sum(attempt.provider_result is not None for attempt in result.attempts),
        total_duration_seconds=result.total_duration_seconds,
        diagnosis_duration_seconds=diagnosis_duration_seconds,
        provider_duration_seconds=sum(
            attempt.provider_result.duration_seconds
            for attempt in result.attempts
            if attempt.provider_result is not None
        ),
        compile_duration_seconds=sum(
            _execution_duration(attempt.compile_result) for attempt in result.attempts
        ),
        test_duration_seconds=sum(
            _execution_duration(attempt.test_result) for attempt in result.attempts
        ),
        files_changed=(
            representative.patch_analysis.stats.files_changed
            if representative and representative.patch_analysis
            else 0
        ),
        lines_added=representative.lines_added if representative else 0,
        lines_removed=representative.lines_removed if representative else 0,
        verification_status=(
            result.verification.status.value if result.verification else None
        ),
        failure_reason=reason,
        run_id=result.run_id,
        run_artifact_path=result.artifact_directory,
        winning_attempt=result.winning_attempt,
        failure_domain=failure_domain(result, reason, provider_failure),
        provider_failure_kind=provider_failure,
    )


def _source_kind(path: Path) -> SourceFileKind:
    if "target" in path.parts and "generated-sources" in path.parts:
        return SourceFileKind.GENERATED_SOURCE
    if tuple(path.parts[:3]) == ("src", "test", "java"):
        return SourceFileKind.TEST_SOURCE
    return SourceFileKind.PRODUCTION_SOURCE


def _execution_duration(execution: object) -> float:
    if execution is None:
        return 0.0
    return sum(command.duration_seconds for command in execution.commands)


def _failure_reason(result: RepairResult) -> FailureReason | None:
    if result.status is MigrationStatus.VERIFIED_MIGRATION:
        return None
    if result.status is MigrationStatus.NEEDS_HUMAN_REVIEW:
        return FailureReason.PATCH_SCOPE_REVIEW
    if not result.attempts:
        return FailureReason.PLAN_NOT_ACTIONABLE
    status = result.attempts[-1].status.value
    mapping = {
        "PROVIDER_ERROR": FailureReason.PROVIDER_FAILED,
        "TIMEOUT": FailureReason.PROVIDER_FAILED,
        "NO_CHANGES": FailureReason.NO_PATCH,
        "COMPILE_FAILED": FailureReason.COMPILE_FAILED,
        "TEST_FAILED": FailureReason.TEST_FAILED,
        "PATCH_REJECTED": FailureReason.DEPENDENCY_GUARD,
        "VERIFICATION_FAILED": FailureReason.TEST_INTEGRITY_VIOLATION,
        "EXECUTION_ERROR": FailureReason.INFRASTRUCTURE_ERROR,
    }
    return mapping.get(status, FailureReason.MAX_ATTEMPTS_EXHAUSTED)


def _hypothesis_migration_kind(value: str) -> MigrationKind:
    mapping = {
        "REMOVED_MEMBER": MigrationKind.REMOVED_METHOD,
        "CHANGED_MEMBER_SIGNATURE": MigrationKind.CHANGED_METHOD_SIGNATURE,
        "REMOVED_CLASS": MigrationKind.REMOVED_CLASS,
        "REMOVED_PACKAGE": MigrationKind.REMOVED_PACKAGE,
        "REMOVED_DEPENDENCY": MigrationKind.REMOVED_DEPENDENCY,
    }
    return mapping.get(value, MigrationKind.UNKNOWN)


def _diagnosis_status(hypothesis_status: str) -> str:
    mapping = {
        "SUPPORTED": "SUPPORTED_DIAGNOSIS",
        "PARTIALLY_SUPPORTED": "PARTIAL_DIAGNOSIS",
        "AMBIGUOUS": "AMBIGUOUS_DIAGNOSIS",
    }
    return mapping.get(hypothesis_status, "INSUFFICIENT_EVIDENCE")


def _api_ground_truth_matches(hypothesis, truth) -> bool:
    if hypothesis is None:
        return False
    if _hypothesis_migration_kind(hypothesis.kind.value) is not truth.failure_kind:
        return False
    evidence_text = "\n".join(
        (
            hypothesis.summary,
            hypothesis.explanation,
            *(item.detail for item in hypothesis.supporting_evidence),
            hypothesis.failure.symbol if hypothesis.failure and hypothesis.failure.symbol else "",
        )
    )
    return all(
        value is None or value in evidence_text
        for value in (truth.class_name, truth.member)
    )
