"""Typed benchmark cases, outcomes, environment facts, and aggregates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bumpshield.models import MigrationKind, TaskSpec


def _text(value: str, name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _identifier(value: str, name: str) -> None:
    _text(value, name)
    if Path(value).name != value or value in {".", ".."}:
        raise ValueError(f"{name} must be a safe single path component")


class BenchmarkCaseType(StrEnum):
    """Relationship between requested and API-breaking dependencies."""

    DIRECT = "DIRECT"
    TRANSITIVE = "TRANSITIVE"
    UNKNOWN = "UNKNOWN"


class BenchmarkSource(StrEnum):
    """Provenance class used when interpreting benchmark evidence."""

    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    REAL_PROJECT = "REAL_PROJECT"


class DatasetSplit(StrEnum):
    """Whether a case may be used for development or is frozen evaluation data."""

    DEV = "DEV"
    ARCHITECTURE = "ARCHITECTURE"
    FINAL = "FINAL"


class UpgradeOrigin(StrEnum):
    """Whether an upgrade came from project history or benchmark construction."""

    HISTORICAL = "HISTORICAL"
    CONSTRUCTED = "CONSTRUCTED"


class BenchmarkValidationStatus(StrEnum):
    """Validity of the claimed base-pass/updated-fail benchmark setup."""

    VALID = "VALID"
    INVALID_CASE = "INVALID_CASE"


class EvaluationFinalStatus(StrEnum):
    """Stable strategy outcome including benchmark infrastructure failure."""

    VERIFIED_MIGRATION = "VERIFIED_MIGRATION"
    UNRESOLVED = "UNRESOLVED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    INVALID_CASE = "INVALID_CASE"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class FailureReason(StrEnum):
    """Coarse deterministic explanation for an unsuccessful strategy result."""

    PROVIDER_FAILED = "PROVIDER_FAILED"
    NO_PATCH = "NO_PATCH"
    COMPILE_FAILED = "COMPILE_FAILED"
    TEST_FAILED = "TEST_FAILED"
    DEPENDENCY_GUARD = "DEPENDENCY_GUARD"
    TEST_INTEGRITY_VIOLATION = "TEST_INTEGRITY_VIOLATION"
    PATCH_SCOPE_REVIEW = "PATCH_SCOPE_REVIEW"
    DIAGNOSIS_INSUFFICIENT = "DIAGNOSIS_INSUFFICIENT"
    PLAN_NOT_ACTIONABLE = "PLAN_NOT_ACTIONABLE"
    MAX_ATTEMPTS_EXHAUSTED = "MAX_ATTEMPTS_EXHAUSTED"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"


class FailureDomain(StrEnum):
    """Research-facing failure ownership, separate from detailed reason."""

    REPAIR = "REPAIR"
    VERIFICATION = "VERIFICATION"
    PROVIDER = "PROVIDER"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    CASE_VALIDATION = "CASE_VALIDATION"


class ProviderFailureKind(StrEnum):
    """Conservative provider failure classes used by circuit breaking."""

    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_QUOTA_EXHAUSTED = "PROVIDER_QUOTA_EXHAUSTED"
    PROVIDER_AUTH_FAILURE = "PROVIDER_AUTH_FAILURE"
    PROVIDER_SERVICE_UNAVAILABLE = "PROVIDER_SERVICE_UNAVAILABLE"
    PROVIDER_NONZERO_EXIT = "PROVIDER_NONZERO_EXIT"
    PROVIDER_UNKNOWN_ERROR = "PROVIDER_UNKNOWN_ERROR"


class BenchmarkRunStatus(StrEnum):
    """Lifecycle state for resumable benchmark execution."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PAUSED_PROVIDER_UNAVAILABLE = "PAUSED_PROVIDER_UNAVAILABLE"
    ABORTED_INFRASTRUCTURE = "ABORTED_INFRASTRUCTURE"
    FAILED_CONFIGURATION = "FAILED_CONFIGURATION"


class StrategyId(StrEnum):
    """Required Phase 8 repair strategies."""

    BUMPSHIELD = "bumpshield"
    DIRECT_ONE_SHOT = "direct-one-shot"
    DIRECT_RETRY = "direct-retry"


BENCHMARK_RESULT_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class GroundTruthDependency:
    """Expected old/new coordinate for the API-breaking artifact."""

    group_id: str
    artifact_id: str
    old_version: str
    new_version: str

    def __post_init__(self) -> None:
        for name in ("group_id", "artifact_id", "old_version", "new_version"):
            _text(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class BenchmarkGroundTruth:
    """Evaluation-only labels that must never enter a repair prompt."""

    breaking_dependency: GroundTruthDependency
    failure_kind: MigrationKind
    class_name: str | None = None
    member: str | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkProvenance:
    """Human-auditable case and ground-truth provenance."""

    project_name: str
    repository_url: str | None
    source_commit: str | None
    license: str | None
    upgrade_origin: UpgradeOrigin
    ground_truth_basis: str

    def __post_init__(self) -> None:
        _text(self.project_name, "provenance project_name")
        _text(self.ground_truth_basis, "provenance ground_truth_basis")


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One known dependency-upgrade regression and optional evaluation labels."""

    id: str
    description: str
    task: TaskSpec
    case_type: BenchmarkCaseType
    source: BenchmarkSource
    split: DatasetSplit = DatasetSplit.DEV
    ground_truth: BenchmarkGroundTruth | None = None
    tags: tuple[str, ...] = ()
    provenance: BenchmarkProvenance | None = None

    def __post_init__(self) -> None:
        _identifier(self.id, "benchmark case id")
        _text(self.description, "benchmark case description")
        if any(not tag.strip() for tag in self.tags):
            raise ValueError("benchmark tags must not be empty")


@dataclass(frozen=True, slots=True)
class BenchmarkSuite:
    """Loaded reproducible benchmark composition."""

    id: str
    cases: tuple[BenchmarkCase, ...]
    strategies: tuple[StrategyId, ...]
    trials: int = 1
    manifest_path: Path | None = None
    evaluation_config_path: Path | None = None
    dataset_lock_path: Path | None = None

    def __post_init__(self) -> None:
        _identifier(self.id, "benchmark suite id")
        if not self.cases:
            raise ValueError("benchmark suite must contain at least one case")
        if not self.strategies:
            raise ValueError("benchmark suite must contain at least one strategy")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("benchmark case IDs must be unique")
        if len(set(self.strategies)) != len(self.strategies):
            raise ValueError("benchmark strategies must be unique")
        if self.trials < 1:
            raise ValueError("benchmark trials must be at least 1")
        if self.manifest_path is not None:
            object.__setattr__(self, "manifest_path", Path(self.manifest_path))
        if self.evaluation_config_path is not None:
            object.__setattr__(
                self, "evaluation_config_path", Path(self.evaluation_config_path)
            )
        if self.dataset_lock_path is not None:
            object.__setattr__(self, "dataset_lock_path", Path(self.dataset_lock_path))


@dataclass(frozen=True, slots=True)
class BenchmarkValidation:
    """Observed case precondition result shared by all strategies."""

    status: BenchmarkValidationStatus
    reason: str | None
    reproduction_status: str | None
    target_versions_matched: bool | None
    artifact_paths: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Provider configuration recorded for strategy fairness auditing."""

    provider: str
    executable: str
    version: str | None
    model: str | None
    timeout_seconds: float
    maximum_attempts: int


@dataclass(frozen=True, slots=True)
class EnvironmentMetadata:
    """Best-effort local environment facts; unavailable tools remain null."""

    platform: str
    python: str
    git: str | None
    java: str | None
    maven: str | None
    codex: str | None
    bumpshield_version: str
    bumpshield_commit: str | None


@dataclass(frozen=True, slots=True)
class BenchmarkCaseResult:
    """One case, strategy, and trial outcome used by all exports."""

    benchmark_run_id: str
    case_id: str
    case_type: BenchmarkCaseType
    case_source: BenchmarkSource
    failure_kind: MigrationKind | None
    strategy: StrategyId
    trial: int
    validation_status: BenchmarkValidationStatus
    final_status: EvaluationFinalStatus
    verified: bool
    root_cause_correct: bool | None = None
    api_change_correct: bool | None = None
    diagnosis_status: str | None = None
    diagnosis_strength: str | None = None
    diagnosis_score: int | None = None
    plan_status: str | None = None
    diagnosed_dependency: str | None = None
    attempt_count: int = 0
    provider_calls: int = 0
    total_duration_seconds: float = 0.0
    diagnosis_duration_seconds: float | None = None
    provider_duration_seconds: float = 0.0
    compile_duration_seconds: float = 0.0
    test_duration_seconds: float = 0.0
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    verification_status: str | None = None
    failure_reason: FailureReason | None = None
    run_id: str | None = None
    run_artifact_path: Path | None = None
    provider_input_tokens: int | None = None
    provider_output_tokens: int | None = None
    provider_cached_tokens: int | None = None
    provider_cost: float | None = None
    schema_version: int = BENCHMARK_RESULT_SCHEMA_VERSION
    execution_position: int | None = None
    attempt_budget: int | None = None
    winning_attempt: int | None = None
    failure_domain: FailureDomain | None = None
    provider_failure_kind: ProviderFailureKind | None = None
    benchmark_config_hash: str | None = None
    verification_policy_version: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.benchmark_run_id, "benchmark run id")
        _identifier(self.case_id, "benchmark case id")
        if self.trial < 1:
            raise ValueError("benchmark trial must be at least 1")
        if self.schema_version < 1:
            raise ValueError("benchmark schema_version must be positive")
        if self.execution_position is not None and self.execution_position < 1:
            raise ValueError("execution_position must be positive")
        if self.attempt_budget is not None and self.attempt_budget < 1:
            raise ValueError("attempt_budget must be positive")
        numeric = (
            self.attempt_count,
            self.provider_calls,
            self.total_duration_seconds,
            self.provider_duration_seconds,
            self.compile_duration_seconds,
            self.test_duration_seconds,
            self.files_changed,
            self.lines_added,
            self.lines_removed,
        )
        if any(value < 0 for value in numeric):
            raise ValueError("benchmark metrics must not be negative")
        if self.verified != (
            self.final_status is EvaluationFinalStatus.VERIFIED_MIGRATION
        ):
            raise ValueError("verified must agree with final_status")
        if self.run_artifact_path is not None:
            object.__setattr__(
                self, "run_artifact_path", Path(self.run_artifact_path)
            )

    @property
    def patch_size(self) -> int:
        """Return added plus removed lines."""
        return self.lines_added + self.lines_removed


@dataclass(frozen=True, slots=True)
class NumericSummary:
    """Mean/median pair, null when no observation exists."""

    mean: float | None
    median: float | None


@dataclass(frozen=True, slots=True)
class StrategyMetrics:
    """Aggregate descriptive metrics for one strategy and result slice."""

    strategy: StrategyId
    attempted_valid: int
    verified: int
    vrr: float | None
    strict_vrr: float | None
    provider_available_trials: int
    provider_available_vrr: float | None
    provider_failures: int
    provider_quota_failures: int
    provider_timeouts: int
    provider_unknown_failures: int
    infrastructure_failures: int
    repair_failures: int
    verification_failures: int
    provider_failure_rate: float | None
    infrastructure_failure_rate: float | None
    repair_failure_rate: float | None
    provider_calls: int
    provider_calls_per_verified: float | None
    unresolved: int
    human_review: int
    execution_errors: int
    attempts: NumericSummary
    attempts_verified: NumericSummary
    repair_time_seconds: NumericSummary
    time_to_verified_seconds: NumericSummary
    diagnosis_time_seconds: NumericSummary
    provider_time_seconds: NumericSummary
    compile_time_seconds: NumericSummary
    test_time_seconds: NumericSummary
    patch_size: NumericSummary
    patch_size_verified: NumericSummary
    out_of_scope_rate: float | None
    verification_rejection_rate: float | None
    diagnosis_success_rate: float | None
    failure_reasons: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class RootCauseMetrics:
    """BumpShield diagnosis correctness for labeled valid trials."""

    dependency_labeled: int
    dependency_correct: int
    dependency_accuracy: float | None
    api_labeled: int
    api_correct: int
    api_accuracy: float | None


@dataclass(frozen=True, slots=True)
class ComparativeMetrics:
    """BumpShield minus direct-one-shot descriptive differences."""

    vrr_difference: float | None
    mean_attempt_difference: float | None
    mean_patch_size_difference: float | None
    mean_runtime_seconds_difference: float | None
    matched_retry_vrr_difference: float | None = None
    direct_retry_gain_over_one_shot: float | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkSummary:
    """Deterministic aggregate benchmark report."""

    benchmark_run_id: str
    suite_id: str
    total_cases: int
    valid_cases: int
    invalid_cases: int
    total_results: int
    overall: tuple[StrategyMetrics, ...]
    direct: tuple[StrategyMetrics, ...]
    transitive: tuple[StrategyMetrics, ...]
    by_failure_type: tuple[tuple[str, tuple[StrategyMetrics, ...]], ...]
    root_cause: RootCauseMetrics
    comparison: ComparativeMetrics
    schema_version: int = BENCHMARK_RESULT_SCHEMA_VERSION
    run_status: BenchmarkRunStatus = BenchmarkRunStatus.COMPLETED
    planned_trials: int = 0
    attempted_trials: int = 0
    completed_trials: int = 0
    unexecuted_trials: int = 0


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    """One deterministic counterbalanced execution slot."""

    case_id: str
    trial: int
    strategy: StrategyId
    execution_position: int

    def __post_init__(self) -> None:
        _identifier(self.case_id, "schedule case id")
        if self.trial < 1 or self.execution_position < 1:
            raise ValueError("schedule trial and position must be positive")


@dataclass(frozen=True, slots=True)
class BenchmarkDryRun:
    """Execution-free benchmark cost preview."""

    suite_id: str
    case_count: int
    strategies: tuple[StrategyId, ...]
    trials: int
    planned_trials: int
    maximum_provider_calls: int
    provider_call_budgets: tuple[tuple[StrategyId, int], ...] = ()
    schedule: tuple[ScheduleEntry, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkRunResult:
    """Completed benchmark run plus external artifact location."""

    benchmark_run_id: str
    suite_id: str
    artifact_directory: Path
    results: tuple[BenchmarkCaseResult, ...]
    summary: BenchmarkSummary
    status: BenchmarkRunStatus = BenchmarkRunStatus.COMPLETED
    planned_trials: int = 0
    attempted_trials: int = 0
    completed_trials: int = 0
    unexecuted_trials: int = 0
    benchmark_config_hash: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.benchmark_run_id, "benchmark run id")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))
