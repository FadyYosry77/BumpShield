"""CSV, JSON, and neutral Markdown benchmark reporting."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from bumpshield.evaluation.models import (
    BenchmarkCaseResult,
    BenchmarkSummary,
    EnvironmentMetadata,
    ProviderMetadata,
    StrategyMetrics,
)
from bumpshield.evaluation.serialization import jsonable

CSV_FIELDS = (
    "schema_version",
    "benchmark_run_id",
    "case_id",
    "case_type",
    "case_source",
    "failure_kind",
    "strategy",
    "trial",
    "execution_position",
    "attempt_budget",
    "valid",
    "final_status",
    "verified",
    "root_cause_correct",
    "attempt_count",
    "provider_calls",
    "total_duration_seconds",
    "diagnosis_duration_seconds",
    "provider_duration_seconds",
    "compile_duration_seconds",
    "test_duration_seconds",
    "files_changed",
    "lines_added",
    "lines_removed",
    "patch_size",
    "failure_reason",
    "failure_domain",
    "provider_failure_kind",
    "winning_attempt",
    "benchmark_config_hash",
    "verification_policy_version",
    "run_id",
    "provider_input_tokens",
    "provider_output_tokens",
    "provider_cached_tokens",
    "provider_cost",
)


class BenchmarkReporter:
    """Persist deterministic aggregate artifacts in one external run directory."""

    def persist(
        self,
        directory: Path,
        results: tuple[BenchmarkCaseResult, ...],
        summary: BenchmarkSummary,
        environment: EnvironmentMetadata,
        provider: ProviderMetadata,
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        ordered = tuple(sorted(results, key=_key))
        self._json(directory / "results.json", ordered)
        self._json(directory / "summary.json", summary)
        self._json(directory / "environment.json", environment)
        self._json(directory / "provider.json", provider)
        self._csv(directory / "results.csv", ordered)
        (directory / "summary.md").write_text(
            render_markdown(summary, environment, provider), encoding="utf-8"
        )

    def _json(self, path: Path, value: object) -> None:
        path.write_text(
            json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _csv(self, path: Path, results: tuple[BenchmarkCaseResult, ...]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for result in results:
                writer.writerow(_csv_row(result))


def render_markdown(
    summary: BenchmarkSummary,
    environment: EnvironmentMetadata,
    provider: ProviderMetadata,
) -> str:
    """Render descriptive results without unsupported causal claims."""
    lines = [
        "# BumpShield Benchmark Results",
        "",
        "## Configuration",
        "",
        f"- Suite: `{summary.suite_id}`",
        f"- Run: `{summary.benchmark_run_id}`",
        f"- Provider: `{provider.provider}`",
        f"- Maximum BumpShield attempts: {provider.maximum_attempts}",
        "",
        "## Environment",
        "",
        f"- Platform: {environment.platform}",
        f"- Python: {environment.python}",
        f"- Git: {environment.git or 'unavailable'}",
        f"- Java: {environment.java or 'unavailable'}",
        f"- Maven: {environment.maven or 'unavailable'}",
        f"- Codex: {environment.codex or 'unavailable'}",
        "",
        "## Dataset",
        "",
        f"- Cases: {summary.total_cases}",
        f"- Valid: {summary.valid_cases}",
        f"- Invalid: {summary.invalid_cases}",
        f"- Run status: `{summary.run_status.value}`",
        f"- Planned trials: {summary.planned_trials}",
        f"- Attempted valid trials: {summary.attempted_trials}",
        f"- Completed rows: {summary.completed_trials}",
        f"- Unexecuted trials: {summary.unexecuted_trials}",
        "",
        "## Overall Results",
        "",
        "| Strategy | Verified | Attempted | Strict VRR | Provider failures |",
        "|---|---:|---:|---:|---:|",
        *(_metric_rows(summary.overall)),
        "",
        "Strict VRR is primary and includes attempted provider failures.",
        "",
        "## Provider-Available VRR (Secondary)",
        "",
        "| Strategy | Provider-available trials | Verified | Conditional VRR |",
        "|---|---:|---:|---:|",
        *(_provider_available_rows(summary.overall)),
        "",
        "## Direct Dependency Cases",
        "",
        "| Strategy | Verified | Attempted | Strict VRR | Provider failures |",
        "|---|---:|---:|---:|---:|",
        *(_metric_rows(summary.direct)),
        "",
        "## Transitive Dependency Cases",
        "",
        "| Strategy | Verified | Attempted | Strict VRR | Provider failures |",
        "|---|---:|---:|---:|---:|",
        *(_metric_rows(summary.transitive)),
        "",
        "## Root Cause Localization",
        "",
        (
            "BumpShield dependency accuracy: "
            f"{summary.root_cause.dependency_correct}/"
            f"{summary.root_cause.dependency_labeled} "
            f"({_percent(summary.root_cause.dependency_accuracy)})."
        ),
        (
            "BumpShield API-change accuracy: "
            f"{summary.root_cause.api_correct}/"
            f"{summary.root_cause.api_labeled} "
            f"({_percent(summary.root_cause.api_accuracy)})."
        ),
        *(
            f"{item.strategy.value} diagnosis success rate: "
            f"{_percent(item.diagnosis_success_rate)}."
            for item in summary.overall
            if item.diagnosis_success_rate is not None
        ),
        "",
        "## Comparative Metrics",
        "",
        (
            "BumpShield minus direct-one-shot VRR: "
            f"{_percentage_points(summary.comparison.vrr_difference)}"
        ),
        (
            "BumpShield minus direct-one-shot mean attempts: "
            f"{_number(summary.comparison.mean_attempt_difference)}"
        ),
        (
            "BumpShield minus direct-one-shot mean patch size: "
            f"{_number(summary.comparison.mean_patch_size_difference)}"
        ),
        (
            "BumpShield minus direct-one-shot mean runtime seconds: "
            f"{_number(summary.comparison.mean_runtime_seconds_difference)}"
        ),
        (
            "BumpShield minus direct-retry strict VRR: "
            f"{_percentage_points(summary.comparison.matched_retry_vrr_difference)}"
        ),
        (
            "Direct-retry minus direct-one-shot strict VRR: "
            f"{_percentage_points(summary.comparison.direct_retry_gain_over_one_shot)}"
        ),
        "",
        "## Repair Attempts",
        "",
        *(_numeric_lines(summary.overall, "attempts")),
        "",
        "Verified repairs only:",
        *(_numeric_lines(summary.overall, "attempts_verified")),
        "",
        "## Runtime",
        "",
        *(_numeric_lines(summary.overall, "repair_time_seconds")),
        "",
        "Time to verified repair:",
        *(_numeric_lines(summary.overall, "time_to_verified_seconds")),
        "",
        "Diagnosis/planning runtime (BumpShield only where available):",
        *(_numeric_lines(summary.overall, "diagnosis_time_seconds")),
        "",
        "## Patch Size",
        "",
        *(_numeric_lines(summary.overall, "patch_size")),
        "",
        "Verified repairs only:",
        *(_numeric_lines(summary.overall, "patch_size_verified")),
        "",
        "## Provider and Infrastructure",
        "",
        *(_provider_lines(summary.overall)),
        "",
        "## Failure Domains",
        "",
        *(_domain_lines(summary.overall)),
        "",
        "## Failure Analysis",
        "",
        *(_failure_lines(summary.overall)),
        "",
        "## Limitations",
        "",
        "These are descriptive results. Development fixtures are not an unseen final dataset, model output may vary, and small samples do not establish statistical significance.",
        "",
    ]
    return "\n".join(lines)


def _csv_row(result: BenchmarkCaseResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "benchmark_run_id": result.benchmark_run_id,
        "case_id": result.case_id,
        "case_type": result.case_type.value,
        "case_source": result.case_source.value,
        "failure_kind": result.failure_kind.value if result.failure_kind else "",
        "strategy": result.strategy.value,
        "trial": result.trial,
        "execution_position": _optional(result.execution_position),
        "attempt_budget": _optional(result.attempt_budget),
        "valid": result.validation_status.value == "VALID",
        "final_status": result.final_status.value,
        "verified": result.verified,
        "root_cause_correct": (
            "" if result.root_cause_correct is None else result.root_cause_correct
        ),
        "attempt_count": result.attempt_count,
        "provider_calls": result.provider_calls,
        "total_duration_seconds": result.total_duration_seconds,
        "diagnosis_duration_seconds": _optional(
            result.diagnosis_duration_seconds
        ),
        "provider_duration_seconds": result.provider_duration_seconds,
        "compile_duration_seconds": result.compile_duration_seconds,
        "test_duration_seconds": result.test_duration_seconds,
        "files_changed": result.files_changed,
        "lines_added": result.lines_added,
        "lines_removed": result.lines_removed,
        "patch_size": result.patch_size,
        "failure_reason": result.failure_reason.value if result.failure_reason else "",
        "failure_domain": result.failure_domain.value if result.failure_domain else "",
        "provider_failure_kind": (
            result.provider_failure_kind.value if result.provider_failure_kind else ""
        ),
        "winning_attempt": _optional(result.winning_attempt),
        "benchmark_config_hash": result.benchmark_config_hash or "",
        "verification_policy_version": result.verification_policy_version or "",
        "run_id": result.run_id or "",
        "provider_input_tokens": _optional(result.provider_input_tokens),
        "provider_output_tokens": _optional(result.provider_output_tokens),
        "provider_cached_tokens": _optional(result.provider_cached_tokens),
        "provider_cost": _optional(result.provider_cost),
    }


def _metric_rows(metrics: tuple[StrategyMetrics, ...]) -> list[str]:
    return [
        f"| {item.strategy.value} | {item.verified} | {item.attempted_valid} | {_percent(item.strict_vrr)} | {item.provider_failures} |"
        for item in metrics
    ]


def _provider_available_rows(metrics: tuple[StrategyMetrics, ...]) -> list[str]:
    return [
        f"| {item.strategy.value} | {item.provider_available_trials} | {item.verified} | {_percent(item.provider_available_vrr)} |"
        for item in metrics
    ]


def _numeric_lines(metrics: tuple[StrategyMetrics, ...], field: str) -> list[str]:
    lines: list[str] = []
    for item in metrics:
        value = getattr(item, field)
        lines.append(
            f"- {item.strategy.value}: mean {_number(value.mean)}, median {_number(value.median)}"
        )
    return lines


def _failure_lines(metrics: tuple[StrategyMetrics, ...]) -> list[str]:
    lines: list[str] = []
    for item in metrics:
        reasons = ", ".join(f"{name}={count}" for name, count in item.failure_reasons)
        lines.append(f"- {item.strategy.value}: {reasons or 'none'}")
    return lines


def _provider_lines(metrics: tuple[StrategyMetrics, ...]) -> list[str]:
    return [
        (
            f"- {item.strategy.value}: calls={item.provider_calls}, "
            f"calls/verified={_number(item.provider_calls_per_verified)}, "
            f"provider failures={item.provider_failures}, "
            f"quota={item.provider_quota_failures}, timeouts={item.provider_timeouts}, "
            f"unknown={item.provider_unknown_failures}, "
            f"provider failure rate={_percent(item.provider_failure_rate)}"
        )
        for item in metrics
    ]


def _domain_lines(metrics: tuple[StrategyMetrics, ...]) -> list[str]:
    return [
        (
            f"- {item.strategy.value}: repair={item.repair_failures}, "
            f"verification={item.verification_failures}, "
            f"provider={item.provider_failures}, "
            f"infrastructure={item.infrastructure_failures}, "
            f"repair failure rate={_percent(item.repair_failure_rate)}, "
            f"infrastructure failure rate={_percent(item.infrastructure_failure_rate)}"
        )
        for item in metrics
    ]


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _percentage_points(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.1f} percentage points"


def _key(result: BenchmarkCaseResult) -> tuple[str, str, int]:
    return result.case_id, result.strategy.value, result.trial


def _optional(value: object | None) -> object:
    return "" if value is None else value
