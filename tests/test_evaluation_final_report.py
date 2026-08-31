from pathlib import Path

from bumpshield.evaluation.dataset import DatasetLockResult
from bumpshield.evaluation.final_report import FinalResearchReporter, paired_analysis
from bumpshield.evaluation.metrics import summarize_benchmark
from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkCaseType,
    BenchmarkRunResult,
    BenchmarkSource,
    BenchmarkSuite,
    BenchmarkValidationStatus,
    EvaluationFinalStatus,
    StrategyId,
)
from bumpshield.models import DependencyUpgrade, TaskSpec


def _result(strategy: StrategyId, verified: bool) -> BenchmarkCaseResult:
    status = (
        EvaluationFinalStatus.VERIFIED_MIGRATION
        if verified
        else EvaluationFinalStatus.UNRESOLVED
    )
    return BenchmarkCaseResult(
        "run",
        "case",
        BenchmarkCaseType.TRANSITIVE,
        BenchmarkSource.SYNTHETIC_FIXTURE,
        None,
        strategy,
        1,
        BenchmarkValidationStatus.VALID,
        status,
        verified,
        attempt_count=1,
        provider_calls=1,
    )


def test_final_report_persists_paired_and_case_level_analysis(tmp_path: Path) -> None:
    results = (
        _result(StrategyId.DIRECT_ONE_SHOT, False),
        _result(StrategyId.DIRECT_RETRY, False),
        _result(StrategyId.BUMPSHIELD, True),
    )
    case = BenchmarkCase(
        "case",
        "fixture",
        TaskSpec(
            tmp_path / "repo",
            "base",
            "updated",
            DependencyUpgrade("org.example", "core", "1", "2"),
        ),
        BenchmarkCaseType.TRANSITIVE,
        BenchmarkSource.SYNTHETIC_FIXTURE,
    )
    suite = BenchmarkSuite(
        "BUMP-FINAL-v1",
        (case,),
        (
            StrategyId.DIRECT_ONE_SHOT,
            StrategyId.DIRECT_RETRY,
            StrategyId.BUMPSHIELD,
        ),
    )
    summary = summarize_benchmark("run", suite.id, 1, results)
    run = BenchmarkRunResult("run", suite.id, tmp_path, results, summary)
    dataset = DatasetLockResult(suite.id, "d" * 64, "c" * 64, 1, 0, 1)

    FinalResearchReporter().persist(suite, run, dataset)
    paired = paired_analysis(results)

    assert paired.bumpshield_vs_direct_retry.left_only == 1
    assert paired.transitive_bumpshield_vs_direct_retry.left_only == 1
    assert (tmp_path / "paired-analysis.json").is_file()
    report = (tmp_path / "final-research-results.md").read_text(encoding="utf-8")
    assert "Strict Verified Repair Rate" in report
    assert "BumpShield vs Direct Retry" in report
    assert "Case-level outcomes" in report
