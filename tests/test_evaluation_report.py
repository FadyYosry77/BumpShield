from pathlib import Path

from bumpshield.evaluation.metrics import summarize_benchmark
from bumpshield.evaluation.models import (
    BenchmarkCaseResult,
    BenchmarkCaseType,
    BenchmarkSource,
    BenchmarkValidationStatus,
    EnvironmentMetadata,
    EvaluationFinalStatus,
    ProviderMetadata,
    StrategyId,
)
from bumpshield.evaluation.report import BenchmarkReporter


def test_csv_json_markdown_exports_are_deterministic(tmp_path: Path) -> None:
    result = BenchmarkCaseResult(
        "run",
        "case",
        BenchmarkCaseType.DIRECT,
        BenchmarkSource.SYNTHETIC_FIXTURE,
        None,
        StrategyId.DIRECT_ONE_SHOT,
        1,
        BenchmarkValidationStatus.VALID,
        EvaluationFinalStatus.VERIFIED_MIGRATION,
        True,
        attempt_count=1,
        lines_added=2,
        lines_removed=1,
    )
    summary = summarize_benchmark("run", "suite", 1, (result,))
    environment = EnvironmentMetadata("linux", "3.12", "git", None, None, None, "0.1", None)
    provider = ProviderMetadata("codex", "codex", None, None, 30, 3)
    first = tmp_path / "first"
    second = tmp_path / "second"

    reporter = BenchmarkReporter()
    reporter.persist(first, (result,), summary, environment, provider)
    reporter.persist(second, (result,), summary, environment, provider)

    for name in ("results.csv", "results.json", "summary.json", "summary.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert "patch_size" in (first / "results.csv").read_text()
    assert "descriptive results" in (first / "summary.md").read_text()
