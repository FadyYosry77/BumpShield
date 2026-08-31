"""Deterministic descriptive benchmark metric calculation."""

from __future__ import annotations

from collections import Counter
from statistics import mean, median

from bumpshield.evaluation.models import (
    BenchmarkCaseResult,
    BenchmarkCaseType,
    BenchmarkSummary,
    BenchmarkRunStatus,
    BenchmarkValidationStatus,
    ComparativeMetrics,
    EvaluationFinalStatus,
    FailureDomain,
    FailureReason,
    ProviderFailureKind,
    NumericSummary,
    RootCauseMetrics,
    StrategyId,
    StrategyMetrics,
)


def summarize_benchmark(
    benchmark_run_id: str,
    suite_id: str,
    case_count: int,
    results: tuple[BenchmarkCaseResult, ...],
    *,
    run_status: BenchmarkRunStatus = BenchmarkRunStatus.COMPLETED,
    planned_trials: int | None = None,
) -> BenchmarkSummary:
    """Aggregate valid trials while counting invalid benchmark cases explicitly."""
    ordered = tuple(sorted(results, key=_result_key))
    strategies = tuple(sorted({item.strategy for item in ordered}, key=str))
    valid_case_ids = {
        item.case_id
        for item in ordered
        if item.validation_status is BenchmarkValidationStatus.VALID
    }
    invalid_case_ids = {item.case_id for item in ordered} - valid_case_ids
    failure_types = sorted(
        {item.failure_kind.value for item in ordered if item.failure_kind is not None}
    )
    overall = tuple(_strategy_metrics(strategy, ordered) for strategy in strategies)
    return BenchmarkSummary(
        benchmark_run_id=benchmark_run_id,
        suite_id=suite_id,
        total_cases=case_count,
        valid_cases=len(valid_case_ids),
        invalid_cases=len(invalid_case_ids),
        total_results=len(ordered),
        overall=overall,
        direct=tuple(
            _strategy_metrics(
                strategy,
                tuple(item for item in ordered if item.case_type is BenchmarkCaseType.DIRECT),
            )
            for strategy in strategies
        ),
        transitive=tuple(
            _strategy_metrics(
                strategy,
                tuple(
                    item
                    for item in ordered
                    if item.case_type is BenchmarkCaseType.TRANSITIVE
                ),
            )
            for strategy in strategies
        ),
        by_failure_type=tuple(
            (
                failure_kind,
                tuple(
                    _strategy_metrics(
                        strategy,
                        tuple(
                            item
                            for item in ordered
                            if item.failure_kind is not None
                            and item.failure_kind.value == failure_kind
                        ),
                    )
                    for strategy in strategies
                ),
            )
            for failure_kind in failure_types
        ),
        root_cause=_root_cause_metrics(ordered),
        comparison=_comparison(overall),
        run_status=run_status,
        planned_trials=(len(ordered) if planned_trials is None else planned_trials),
        attempted_trials=sum(
            item.validation_status is BenchmarkValidationStatus.VALID
            for item in ordered
        ),
        completed_trials=len(ordered),
        unexecuted_trials=max(
            0, (len(ordered) if planned_trials is None else planned_trials) - len(ordered)
        ),
    )


def _strategy_metrics(
    strategy: StrategyId,
    results: tuple[BenchmarkCaseResult, ...],
) -> StrategyMetrics:
    selected = tuple(
        item
        for item in results
        if item.strategy is strategy
        and item.validation_status is BenchmarkValidationStatus.VALID
    )
    verified = sum(item.verified for item in selected)
    domains = tuple(_failure_domain(item) for item in selected)
    provider_failures = sum(domain is FailureDomain.PROVIDER for domain in domains)
    infrastructure_failures = sum(
        domain is FailureDomain.INFRASTRUCTURE for domain in domains
    )
    repair_failures = sum(domain is FailureDomain.REPAIR for domain in domains)
    verification_failures = sum(
        domain is FailureDomain.VERIFICATION for domain in domains
    )
    provider_available = tuple(
        item
        for item, domain in zip(selected, domains, strict=True)
        if domain not in {FailureDomain.PROVIDER, FailureDomain.INFRASTRUCTURE}
    )
    verified_results = tuple(item for item in selected if item.verified)
    provider_calls = sum(item.provider_calls for item in selected)
    reasons = Counter(
        item.failure_reason.value
        for item in selected
        if item.failure_reason is not None
    )
    verification_rejections = sum(
        item.verification_status in {"VERIFICATION_FAILED", "NEEDS_HUMAN_REVIEW"}
        for item in selected
    )
    out_of_scope = sum(
        item.failure_reason is not None
        and item.failure_reason.value == "PATCH_SCOPE_REVIEW"
        for item in selected
    )
    return StrategyMetrics(
        strategy=strategy,
        attempted_valid=len(selected),
        verified=verified,
        vrr=_ratio(verified, len(selected)),
        strict_vrr=_ratio(verified, len(selected)),
        provider_available_trials=len(provider_available),
        provider_available_vrr=_ratio(
            sum(item.verified for item in provider_available),
            len(provider_available),
        ),
        provider_failures=provider_failures,
        provider_quota_failures=sum(
            item.provider_failure_kind
            is ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED
            for item in selected
        ),
        provider_timeouts=sum(
            item.provider_failure_kind is ProviderFailureKind.PROVIDER_TIMEOUT
            for item in selected
        ),
        provider_unknown_failures=sum(
            domain is FailureDomain.PROVIDER
            and item.provider_failure_kind
            in {
                None,
                ProviderFailureKind.PROVIDER_UNKNOWN_ERROR,
                ProviderFailureKind.PROVIDER_NONZERO_EXIT,
            }
            for item, domain in zip(selected, domains, strict=True)
        ),
        infrastructure_failures=infrastructure_failures,
        repair_failures=repair_failures,
        verification_failures=verification_failures,
        provider_failure_rate=_ratio(provider_failures, len(selected)),
        infrastructure_failure_rate=_ratio(
            provider_failures + infrastructure_failures, len(selected)
        ),
        repair_failure_rate=_ratio(repair_failures, len(provider_available)),
        provider_calls=provider_calls,
        provider_calls_per_verified=(
            provider_calls / verified if verified else None
        ),
        unresolved=sum(
            item.final_status is EvaluationFinalStatus.UNRESOLVED for item in selected
        ),
        human_review=sum(
            item.final_status is EvaluationFinalStatus.NEEDS_HUMAN_REVIEW
            for item in selected
        ),
        execution_errors=sum(
            item.final_status is EvaluationFinalStatus.EXECUTION_ERROR
            for item in selected
        ),
        attempts=_numbers(tuple(float(item.attempt_count) for item in selected)),
        attempts_verified=_numbers(
            tuple(float(item.attempt_count) for item in verified_results)
        ),
        repair_time_seconds=_numbers(
            tuple(item.total_duration_seconds for item in selected)
        ),
        time_to_verified_seconds=_numbers(
            tuple(item.total_duration_seconds for item in verified_results)
        ),
        diagnosis_time_seconds=_numbers(
            tuple(
                item.diagnosis_duration_seconds
                for item in selected
                if item.diagnosis_duration_seconds is not None
            )
        ),
        provider_time_seconds=_numbers(
            tuple(item.provider_duration_seconds for item in selected)
        ),
        compile_time_seconds=_numbers(
            tuple(item.compile_duration_seconds for item in selected)
        ),
        test_time_seconds=_numbers(
            tuple(item.test_duration_seconds for item in selected)
        ),
        patch_size=_numbers(tuple(float(item.patch_size) for item in selected)),
        patch_size_verified=_numbers(
            tuple(float(item.patch_size) for item in verified_results)
        ),
        out_of_scope_rate=_ratio(out_of_scope, len(selected)),
        verification_rejection_rate=_ratio(
            verification_rejections, len(selected)
        ),
        diagnosis_success_rate=_ratio(
            sum(
                item.diagnosis_status in {"SUPPORTED", "SUPPORTED_DIAGNOSIS"}
                for item in selected
            ),
            sum(item.diagnosis_status is not None for item in selected),
        ),
        failure_reasons=tuple(sorted(reasons.items())),
    )


def _root_cause_metrics(
    results: tuple[BenchmarkCaseResult, ...],
) -> RootCauseMetrics:
    selected = tuple(
        item
        for item in results
        if item.strategy is StrategyId.BUMPSHIELD
        and item.validation_status is BenchmarkValidationStatus.VALID
    )
    dependency = tuple(item for item in selected if item.root_cause_correct is not None)
    api = tuple(item for item in selected if item.api_change_correct is not None)
    dependency_correct = sum(item.root_cause_correct is True for item in dependency)
    api_correct = sum(item.api_change_correct is True for item in api)
    return RootCauseMetrics(
        dependency_labeled=len(dependency),
        dependency_correct=dependency_correct,
        dependency_accuracy=_ratio(dependency_correct, len(dependency)),
        api_labeled=len(api),
        api_correct=api_correct,
        api_accuracy=_ratio(api_correct, len(api)),
    )


def _numbers(values: tuple[float, ...]) -> NumericSummary:
    return NumericSummary(
        mean=mean(values) if values else None,
        median=median(values) if values else None,
    )


def _comparison(metrics: tuple[StrategyMetrics, ...]) -> ComparativeMetrics:
    indexed = {item.strategy: item for item in metrics}
    bumpshield = indexed.get(StrategyId.BUMPSHIELD)
    baseline = indexed.get(StrategyId.DIRECT_ONE_SHOT)
    retry = indexed.get(StrategyId.DIRECT_RETRY)
    return ComparativeMetrics(
        vrr_difference=_difference(
            bumpshield.vrr if bumpshield else None,
            baseline.vrr if baseline else None,
        ),
        mean_attempt_difference=_difference(
            bumpshield.attempts.mean if bumpshield else None,
            baseline.attempts.mean if baseline else None,
        ),
        mean_patch_size_difference=_difference(
            bumpshield.patch_size.mean if bumpshield else None,
            baseline.patch_size.mean if baseline else None,
        ),
        mean_runtime_seconds_difference=_difference(
            bumpshield.repair_time_seconds.mean if bumpshield else None,
            baseline.repair_time_seconds.mean if baseline else None,
        ),
        matched_retry_vrr_difference=_difference(
            bumpshield.strict_vrr if bumpshield else None,
            retry.strict_vrr if retry else None,
        ),
        direct_retry_gain_over_one_shot=_difference(
            retry.strict_vrr if retry else None,
            baseline.strict_vrr if baseline else None,
        ),
    )


def _failure_domain(result: BenchmarkCaseResult) -> FailureDomain | None:
    if result.failure_domain is not None:
        return result.failure_domain
    if result.failure_reason is FailureReason.PROVIDER_FAILED:
        return FailureDomain.PROVIDER
    if result.failure_reason is FailureReason.INFRASTRUCTURE_ERROR:
        return FailureDomain.INFRASTRUCTURE
    if result.failure_reason in {
        FailureReason.DEPENDENCY_GUARD,
        FailureReason.TEST_INTEGRITY_VIOLATION,
        FailureReason.PATCH_SCOPE_REVIEW,
    }:
        return FailureDomain.VERIFICATION
    if result.verified or result.failure_reason is None:
        return None
    return FailureDomain.REPAIR


def _difference(left: float | None, right: float | None) -> float | None:
    return left - right if left is not None and right is not None else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _result_key(result: BenchmarkCaseResult) -> tuple[str, str, int]:
    return result.case_id, result.strategy.value, result.trial
