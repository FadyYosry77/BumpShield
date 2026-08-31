"""Structured paired analysis and neutral final-evaluation reporting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

from bumpshield.evaluation.dataset import DatasetLockResult
from bumpshield.evaluation.models import (
    BenchmarkCaseResult,
    BenchmarkCaseType,
    BenchmarkRunResult,
    BenchmarkSource,
    BenchmarkSuite,
    BenchmarkValidationStatus,
    StrategyId,
)
from bumpshield.evaluation.serialization import jsonable


@dataclass(frozen=True, slots=True)
class PairedOutcome:
    """Paired verified outcomes for two strategies on identical trials."""

    left: StrategyId
    right: StrategyId
    case_type: BenchmarkCaseType | None
    both_verified: int
    left_only: int
    right_only: int
    neither: int
    comparable_pairs: int


@dataclass(frozen=True, slots=True)
class FinalPairedAnalysis:
    """All frozen paired comparisons plus case-level outcomes."""

    bumpshield_vs_direct_retry: PairedOutcome
    bumpshield_vs_direct_one_shot: PairedOutcome
    transitive_bumpshield_vs_direct_retry: PairedOutcome
    transitive_bumpshield_vs_direct_one_shot: PairedOutcome


class FinalResearchReporter:
    """Generate final descriptive artifacts from persisted structured results."""

    def persist(
        self,
        suite: BenchmarkSuite,
        run: BenchmarkRunResult,
        dataset: DatasetLockResult,
    ) -> None:
        paired = paired_analysis(run.results)
        directory = run.artifact_directory
        (directory / "paired-analysis.json").write_text(
            json.dumps(jsonable(paired), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (directory / "final-research-results.md").write_text(
            render_final_markdown(suite, run, dataset, paired),
            encoding="utf-8",
        )


def paired_analysis(results: tuple[BenchmarkCaseResult, ...]) -> FinalPairedAnalysis:
    return FinalPairedAnalysis(
        _pair(results, StrategyId.BUMPSHIELD, StrategyId.DIRECT_RETRY),
        _pair(results, StrategyId.BUMPSHIELD, StrategyId.DIRECT_ONE_SHOT),
        _pair(
            results,
            StrategyId.BUMPSHIELD,
            StrategyId.DIRECT_RETRY,
            BenchmarkCaseType.TRANSITIVE,
        ),
        _pair(
            results,
            StrategyId.BUMPSHIELD,
            StrategyId.DIRECT_ONE_SHOT,
            BenchmarkCaseType.TRANSITIVE,
        ),
    )


def render_final_markdown(
    suite: BenchmarkSuite,
    run: BenchmarkRunResult,
    dataset: DatasetLockResult,
    paired: FinalPairedAnalysis,
) -> str:
    """Render neutral final results; no result-dependent algorithmic claims."""
    summary = run.summary
    cases = {case.id: case for case in suite.cases}
    results = tuple(sorted(run.results, key=_key))
    lines = [
        "# BUMP-FINAL-v1 research results",
        "",
        "## Research question",
        "",
        "Does explicit causal dependency analysis improve independently verified repair of breaking Java/Maven dependency upgrades?",
        "",
        "## Frozen evaluation",
        "",
        f"- Configuration hash: `{dataset.config_hash}`",
        f"- Dataset hash: `{dataset.dataset_hash}`",
        f"- Cases: {dataset.case_count} ({dataset.direct_count} direct, {dataset.transitive_count} transitive)",
        f"- Run: `{run.benchmark_run_id}`",
        f"- Run status: `{run.status.value}`",
        f"- Trials: {run.completed_trials}/{run.planned_trials} completed",
        "",
        "## Strict Verified Repair Rate",
        "",
        "| Strategy | Verified | Attempted | Strict VRR |",
        "|---|---:|---:|---:|",
        *(_strategy_rows(summary.overall, "strict_vrr")),
        "",
        "Provider failures remain in strict VRR. Provider-available VRR below is secondary.",
        "",
        "## Provider-available VRR",
        "",
        "| Strategy | Verified | Available trials | VRR |",
        "|---|---:|---:|---:|",
        *(
            f"| {item.strategy.value} | {item.verified} | {item.provider_available_trials} | {_percent(item.provider_available_vrr)} |"
            for item in summary.overall
        ),
        "",
        "## Direct cases",
        "",
        "| Strategy | Verified | Attempted | Strict VRR |",
        "|---|---:|---:|---:|",
        *(_strategy_rows(summary.direct, "strict_vrr")),
        "",
        "## Transitive cases",
        "",
        "| Strategy | Verified | Attempted | Strict VRR |",
        "|---|---:|---:|---:|",
        *(_strategy_rows(summary.transitive, "strict_vrr")),
        "",
        "## Paired outcomes",
        "",
        *(_paired_lines("BumpShield vs Direct Retry", paired.bumpshield_vs_direct_retry)),
        *(_paired_lines("BumpShield vs Direct One-Shot", paired.bumpshield_vs_direct_one_shot)),
        *(_paired_lines("Transitive: BumpShield vs Direct Retry", paired.transitive_bumpshield_vs_direct_retry)),
        "",
        "## Root-cause localization",
        "",
        f"- Dependency: {summary.root_cause.dependency_correct}/{summary.root_cause.dependency_labeled} ({_percent(summary.root_cause.dependency_accuracy)})",
        f"- API change: {summary.root_cause.api_correct}/{summary.root_cause.api_labeled} ({_percent(summary.root_cause.api_accuracy)})",
        *(_root_breakdown(results)),
        "",
        "## Diagnosis and planning",
        "",
        *(_diagnosis_lines(results)),
        "",
        "## Attempts, provider calls, runtime, and patch size",
        "",
        *(_operational_lines(summary.overall, results)),
        "",
        "## Failure types",
        "",
        *(_failure_type_lines(summary.by_failure_type)),
        "",
        "## Case sources",
        "",
        *(_source_lines(results)),
        "",
        "## Case-level outcomes",
        "",
        "| Case | Type | Failure | Source | One-shot | Retry | BumpShield | Root cause correct | BumpShield attempts |",
        "|---|---|---|---|---|---|---|---|---:|",
        *(_case_rows(cases, results)),
        "",
        "## Failure analysis",
        "",
        *(_failure_lines(summary.overall)),
        "",
        "## Limitations",
        "",
        "Results are descriptive for one frozen 20-case benchmark. Model behavior and runtime depend on provider and machine conditions. Synthetic cases do not establish production-project generality. Existing project tests remain the behavioral oracle. No statistical significance is claimed.",
        "",
    ]
    return "\n".join(lines)


def _pair(
    results: tuple[BenchmarkCaseResult, ...],
    left: StrategyId,
    right: StrategyId,
    case_type: BenchmarkCaseType | None = None,
) -> PairedOutcome:
    selected = tuple(
        item
        for item in results
        if item.validation_status is BenchmarkValidationStatus.VALID
        and (case_type is None or item.case_type is case_type)
    )
    indexed = {(item.case_id, item.trial, item.strategy): item for item in selected}
    keys = sorted({(item.case_id, item.trial) for item in selected})
    both = left_only = right_only = neither = comparable = 0
    for case_id, trial in keys:
        left_result = indexed.get((case_id, trial, left))
        right_result = indexed.get((case_id, trial, right))
        if left_result is None or right_result is None:
            continue
        comparable += 1
        if left_result.verified and right_result.verified:
            both += 1
        elif left_result.verified:
            left_only += 1
        elif right_result.verified:
            right_only += 1
        else:
            neither += 1
    return PairedOutcome(
        left, right, case_type, both, left_only, right_only, neither, comparable
    )


def _strategy_rows(metrics, field: str) -> list[str]:
    return [
        f"| {item.strategy.value} | {item.verified} | {item.attempted_valid} | {_percent(getattr(item, field))} |"
        for item in metrics
    ]


def _paired_lines(label: str, pair: PairedOutcome) -> list[str]:
    return [
        f"### {label}",
        "",
        f"Both verified: {pair.both_verified}; {pair.left.value} only: {pair.left_only}; {pair.right.value} only: {pair.right_only}; neither: {pair.neither}; comparable pairs: {pair.comparable_pairs}.",
        "",
    ]


def _root_breakdown(results: tuple[BenchmarkCaseResult, ...]) -> list[str]:
    lines = []
    for kind in (BenchmarkCaseType.DIRECT, BenchmarkCaseType.TRANSITIVE):
        labeled = [
            item
            for item in results
            if item.strategy is StrategyId.BUMPSHIELD
            and item.case_type is kind
            and item.root_cause_correct is not None
        ]
        correct = sum(item.root_cause_correct is True for item in labeled)
        lines.append(f"- {kind.value}: {correct}/{len(labeled)} ({_ratio(correct, len(labeled))})")
    return lines


def _diagnosis_lines(results: tuple[BenchmarkCaseResult, ...]) -> list[str]:
    bumpshield = [item for item in results if item.strategy is StrategyId.BUMPSHIELD]
    statuses: dict[str, int] = {}
    plans: dict[str, int] = {}
    for item in bumpshield:
        statuses[item.diagnosis_status or "UNAVAILABLE"] = statuses.get(item.diagnosis_status or "UNAVAILABLE", 0) + 1
        plans[item.plan_status or "UNAVAILABLE"] = plans.get(item.plan_status or "UNAVAILABLE", 0) + 1
    return [
        "- Diagnosis: " + ", ".join(f"{key}={value}" for key, value in sorted(statuses.items())),
        "- Plans: " + ", ".join(f"{key}={value}" for key, value in sorted(plans.items())),
    ]


def _operational_lines(metrics, results: tuple[BenchmarkCaseResult, ...]) -> list[str]:
    lines = []
    for item in metrics:
        verified = [result for result in results if result.strategy is item.strategy and result.verified]
        files = [float(result.files_changed) for result in verified]
        lines.append(
            f"- {item.strategy.value}: attempts all mean/median {_number(item.attempts.mean)}/{_number(item.attempts.median)}; verified {_number(item.attempts_verified.mean)}/{_number(item.attempts_verified.median)}; calls {item.provider_calls}; calls/verified {_number(item.provider_calls_per_verified)}; runtime all {_number(item.repair_time_seconds.mean)}/{_number(item.repair_time_seconds.median)} s; verified time {_number(item.time_to_verified_seconds.mean)}/{_number(item.time_to_verified_seconds.median)} s; verified files {_number(_mean(files))}/{_number(_median(files))}; verified patch {_number(item.patch_size_verified.mean)}/{_number(item.patch_size_verified.median)} lines."
        )
    return lines


def _failure_type_lines(groups) -> list[str]:
    lines = []
    for failure, metrics in groups:
        values = ", ".join(
            f"{item.strategy.value}={item.verified}/{item.attempted_valid} ({_percent(item.strict_vrr)})"
            for item in metrics
        )
        lines.append(f"- {failure}: {values}")
    return lines or ["- unavailable"]


def _source_lines(results: tuple[BenchmarkCaseResult, ...]) -> list[str]:
    lines = []
    for source in BenchmarkSource:
        selected = [item for item in results if item.case_source is source and item.validation_status is BenchmarkValidationStatus.VALID]
        if not selected:
            continue
        for strategy in StrategyId:
            rows = [item for item in selected if item.strategy is strategy]
            if rows:
                lines.append(f"- {source.value} / {strategy.value}: {sum(item.verified for item in rows)}/{len(rows)} ({_ratio(sum(item.verified for item in rows), len(rows))})")
    return lines or ["- unavailable"]


def _case_rows(cases, results: tuple[BenchmarkCaseResult, ...]) -> list[str]:
    indexed = {(item.case_id, item.strategy): item for item in results}
    lines = []
    for case_id in sorted(cases):
        case = cases[case_id]
        one = indexed.get((case_id, StrategyId.DIRECT_ONE_SHOT))
        retry = indexed.get((case_id, StrategyId.DIRECT_RETRY))
        bump = indexed.get((case_id, StrategyId.BUMPSHIELD))
        lines.append(
            f"| {case_id} | {case.case_type.value} | {case.ground_truth.failure_kind.value if case.ground_truth else 'unlabeled'} | {case.source.value} | {_status(one)} | {_status(retry)} | {_status(bump)} | {_optional_bool(bump.root_cause_correct if bump else None)} | {bump.attempt_count if bump else ''} |"
        )
    return lines


def _failure_lines(metrics) -> list[str]:
    return [
        f"- {item.strategy.value}: provider={item.provider_failures}, infrastructure={item.infrastructure_failures}, repair={item.repair_failures}, verification={item.verification_failures}; reasons "
        + (", ".join(f"{name}={count}" for name, count in item.failure_reasons) or "none")
        for item in metrics
    ]


def _status(result: BenchmarkCaseResult | None) -> str:
    return result.final_status.value if result else "UNEXECUTED"


def _optional_bool(value: bool | None) -> str:
    return "" if value is None else str(value)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _ratio(numerator: int, denominator: int) -> str:
    return "n/a" if not denominator else f"{numerator / denominator * 100:.1f}%"


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _median(values: list[float]) -> float | None:
    return median(values) if values else None


def _key(result: BenchmarkCaseResult) -> tuple[str, str, int]:
    return result.case_id, result.strategy.value, result.trial
