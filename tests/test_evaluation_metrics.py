from dataclasses import replace
from pathlib import Path

from bumpshield.evaluation.metrics import summarize_benchmark
from bumpshield.evaluation.models import (
    BenchmarkCaseResult,
    BenchmarkCaseType,
    BenchmarkSource,
    BenchmarkValidationStatus,
    EvaluationFinalStatus,
    FailureDomain,
    FailureReason,
    ProviderFailureKind,
    StrategyId,
)
from bumpshield.models import MigrationKind


def _result(
    case_id: str,
    case_type: BenchmarkCaseType,
    status: EvaluationFinalStatus,
    *,
    valid: bool = True,
    root: bool | None = None,
    lines: tuple[int, int] = (0, 0),
    domain: FailureDomain | None = None,
    reason: FailureReason | None = None,
    provider_kind: ProviderFailureKind | None = None,
    provider_calls: int = 0,
    duration: float = 2,
) -> BenchmarkCaseResult:
    return BenchmarkCaseResult(
        "run",
        case_id,
        case_type,
        BenchmarkSource.SYNTHETIC_FIXTURE,
        MigrationKind.REMOVED_METHOD,
        StrategyId.BUMPSHIELD,
        1,
        (
            BenchmarkValidationStatus.VALID
            if valid
            else BenchmarkValidationStatus.INVALID_CASE
        ),
        status,
        status is EvaluationFinalStatus.VERIFIED_MIGRATION,
        root_cause_correct=root,
        attempt_count=1,
        total_duration_seconds=duration,
        lines_added=lines[0],
        lines_removed=lines[1],
        run_artifact_path=Path("/tmp/run"),
        failure_domain=domain,
        failure_reason=reason,
        provider_failure_kind=provider_kind,
        provider_calls=provider_calls,
    )


def test_vrr_excludes_invalid_and_groups_direct_transitive() -> None:
    results = (
        _result("d1", BenchmarkCaseType.DIRECT, EvaluationFinalStatus.VERIFIED_MIGRATION, root=True),
        _result("d2", BenchmarkCaseType.DIRECT, EvaluationFinalStatus.UNRESOLVED, root=False),
        _result("t1", BenchmarkCaseType.TRANSITIVE, EvaluationFinalStatus.VERIFIED_MIGRATION, root=True),
        _result("t2", BenchmarkCaseType.TRANSITIVE, EvaluationFinalStatus.UNRESOLVED, root=True),
        _result("bad", BenchmarkCaseType.DIRECT, EvaluationFinalStatus.INVALID_CASE, valid=False),
    )

    summary = summarize_benchmark("run", "suite", 5, results)

    assert summary.valid_cases == 4
    assert summary.invalid_cases == 1
    assert summary.overall[0].vrr == 0.5
    assert summary.direct[0].vrr == 0.5
    assert summary.transitive[0].vrr == 0.5
    assert summary.root_cause.dependency_accuracy == 0.75
    assert summary.overall[0].diagnosis_success_rate is None


def test_patch_size_and_empty_slice_statistics() -> None:
    result = _result(
        "only", BenchmarkCaseType.DIRECT, EvaluationFinalStatus.VERIFIED_MIGRATION, lines=(3, 2)
    )
    summary = summarize_benchmark("run", "suite", 1, (result,))

    assert result.patch_size == 5
    assert summary.overall[0].patch_size.mean == 5
    assert summary.overall[0].patch_size.median == 5
    assert summary.transitive[0].vrr is None
    assert summary.transitive[0].patch_size.mean is None


def test_legacy_supported_diagnosis_counts_as_success() -> None:
    result = _result(
        "only", BenchmarkCaseType.DIRECT, EvaluationFinalStatus.VERIFIED_MIGRATION
    )
    result = replace(result, diagnosis_status="SUPPORTED")

    summary = summarize_benchmark("run", "suite", 1, (result,))

    assert summary.overall[0].diagnosis_success_rate == 1.0


def test_strict_and_provider_available_vrr_keep_distinct_denominators() -> None:
    results = tuple(
        _result(
            f"ok-{index}",
            BenchmarkCaseType.DIRECT,
            EvaluationFinalStatus.VERIFIED_MIGRATION,
            provider_calls=2,
        )
        for index in range(3)
    ) + (
        _result(
            "quota",
            BenchmarkCaseType.DIRECT,
            EvaluationFinalStatus.UNRESOLVED,
            domain=FailureDomain.PROVIDER,
            reason=FailureReason.PROVIDER_FAILED,
            provider_kind=ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED,
            provider_calls=1,
        ),
    )

    metric = summarize_benchmark("run", "suite", 4, results).overall[0]

    assert metric.strict_vrr == 0.75
    assert metric.vrr == 0.75
    assert metric.provider_available_trials == 3
    assert metric.provider_available_vrr == 1.0
    assert metric.provider_failure_rate == 0.25
    assert metric.provider_quota_failures == 1
    assert metric.provider_calls_per_verified == 7 / 3


def test_failure_domains_and_success_only_metrics_do_not_hide_fast_outage() -> None:
    results = (
        _result(
            "success-100",
            BenchmarkCaseType.DIRECT,
            EvaluationFinalStatus.VERIFIED_MIGRATION,
            duration=100,
            lines=(2, 1),
        ),
        _result(
            "success-80",
            BenchmarkCaseType.DIRECT,
            EvaluationFinalStatus.VERIFIED_MIGRATION,
            duration=80,
            lines=(1, 1),
        ),
        _result(
            "compile",
            BenchmarkCaseType.DIRECT,
            EvaluationFinalStatus.UNRESOLVED,
            domain=FailureDomain.REPAIR,
            reason=FailureReason.COMPILE_FAILED,
            duration=60,
        ),
        _result(
            "quota",
            BenchmarkCaseType.DIRECT,
            EvaluationFinalStatus.UNRESOLVED,
            domain=FailureDomain.PROVIDER,
            reason=FailureReason.PROVIDER_FAILED,
            provider_kind=ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED,
            duration=2,
        ),
    )

    metric = summarize_benchmark("run", "suite", 4, results).overall[0]

    assert metric.repair_time_seconds.mean == 60.5
    assert metric.time_to_verified_seconds.mean == 90
    assert metric.patch_size_verified.mean == 2.5
    assert metric.repair_failures == 1
    assert metric.provider_failures == 1
    assert metric.repair_failure_rate == 1 / 3
