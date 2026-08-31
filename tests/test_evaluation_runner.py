import sys
from pathlib import Path

from bumpshield.config import BumpShieldConfig
from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkCaseType,
    BenchmarkRunStatus,
    BenchmarkSource,
    BenchmarkSuite,
    BenchmarkValidation,
    BenchmarkValidationStatus,
    EvaluationFinalStatus,
    FailureDomain,
    FailureReason,
    ProviderFailureKind,
    StrategyId,
)
from bumpshield.evaluation.runner import BenchmarkRunner
from bumpshield.models import DependencyUpgrade, TaskSpec


def _case(tmp_path: Path, case_id: str = "case") -> BenchmarkCase:
    repository = tmp_path / "repo"
    repository.mkdir(exist_ok=True)
    return BenchmarkCase(
        case_id,
        "fixture",
        TaskSpec(
            repository,
            "base",
            "updated",
            DependencyUpgrade("org.example", "core", "1", "2"),
        ),
        BenchmarkCaseType.DIRECT,
        BenchmarkSource.SYNTHETIC_FIXTURE,
    )


class FakeValidator:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.calls = 0

    def validate(self, case):
        self.calls += 1
        return BenchmarkValidation(
            BenchmarkValidationStatus.VALID if self.valid else BenchmarkValidationStatus.INVALID_CASE,
            None if self.valid else "base failed",
            "CONFIRMED" if self.valid else "BASE_FAILED",
            self.valid,
        )


class FakeStrategy:
    maximum_provider_calls = 3

    def __init__(self, strategy_id: StrategyId) -> None:
        self.id = strategy_id
        self.calls = 0

    def run(self, case, benchmark_run_id, trial):
        self.calls += 1
        return BenchmarkCaseResult(
            benchmark_run_id,
            case.id,
            case.case_type,
            case.source,
            None,
            self.id,
            trial,
            BenchmarkValidationStatus.VALID,
            EvaluationFinalStatus.VERIFIED_MIGRATION,
            True,
            attempt_count=1,
        )


class ProviderQuotaStrategy(FakeStrategy):
    def run(self, case, benchmark_run_id, trial):
        self.calls += 1
        return BenchmarkCaseResult(
            benchmark_run_id,
            case.id,
            case.case_type,
            case.source,
            None,
            self.id,
            trial,
            BenchmarkValidationStatus.VALID,
            EvaluationFinalStatus.UNRESOLVED,
            False,
            attempt_count=1,
            provider_calls=1,
            failure_reason=FailureReason.PROVIDER_FAILED,
            failure_domain=FailureDomain.PROVIDER,
            provider_failure_kind=ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED,
        )


def test_dry_run_call_estimate_and_resume(tmp_path: Path) -> None:
    case = _case(tmp_path)
    suite = BenchmarkSuite("suite", (case,), (StrategyId.BUMPSHIELD,), trials=2)
    strategy = FakeStrategy(StrategyId.BUMPSHIELD)
    config = BumpShieldConfig(
        state_root=tmp_path / "state", repair_provider_executable=sys.executable
    )
    validator = FakeValidator()
    runner = BenchmarkRunner(
        config,
        validator=validator,
        strategies={StrategyId.BUMPSHIELD: strategy},
    )

    preview = runner.dry_run(suite)
    first = runner.run(suite, resume_run_id=None)
    resumed = runner.run(suite, resume_run_id=first.benchmark_run_id)

    assert preview.maximum_provider_calls == 6
    assert strategy.calls == 2
    assert validator.calls == 1
    assert len(resumed.results) == 2
    assert (first.artifact_directory / "results.csv").is_file()
    assert (first.artifact_directory / "summary.md").is_file()


def test_invalid_case_is_explicit_and_strategy_not_run(tmp_path: Path) -> None:
    case = _case(tmp_path)
    suite = BenchmarkSuite("suite", (case,), (StrategyId.BUMPSHIELD,))
    strategy = FakeStrategy(StrategyId.BUMPSHIELD)
    runner = BenchmarkRunner(
        BumpShieldConfig(
            state_root=tmp_path / "state", repair_provider_executable=sys.executable
        ),
        validator=FakeValidator(valid=False),
        strategies={StrategyId.BUMPSHIELD: strategy},
    )

    result = runner.run(suite)

    assert strategy.calls == 0
    assert result.results[0].final_status is EvaluationFinalStatus.INVALID_CASE
    assert result.summary.valid_cases == 0
    assert result.summary.invalid_cases == 1


def test_dry_run_counterbalances_three_strategies_and_counts_calls(tmp_path: Path) -> None:
    cases = tuple(_case(tmp_path, f"case-{index}") for index in range(4))
    strategy_ids = (
        StrategyId.DIRECT_ONE_SHOT,
        StrategyId.DIRECT_RETRY,
        StrategyId.BUMPSHIELD,
    )
    strategies = {
        StrategyId.DIRECT_ONE_SHOT: FakeStrategy(StrategyId.DIRECT_ONE_SHOT),
        StrategyId.DIRECT_RETRY: FakeStrategy(StrategyId.DIRECT_RETRY),
        StrategyId.BUMPSHIELD: FakeStrategy(StrategyId.BUMPSHIELD),
    }
    strategies[StrategyId.DIRECT_ONE_SHOT].maximum_provider_calls = 1
    suite = BenchmarkSuite("suite", cases, strategy_ids)
    runner = BenchmarkRunner(
        BumpShieldConfig(
            state_root=tmp_path / "state", repair_provider_executable=sys.executable
        ),
        validator=FakeValidator(),
        strategies=strategies,
    )

    preview = runner.dry_run(suite)

    assert preview.maximum_provider_calls == 28
    assert [entry.execution_position for entry in preview.schedule] == [1, 2, 3] * 4
    assert [entry.strategy for entry in preview.schedule[:6]] == [
        StrategyId.DIRECT_ONE_SHOT,
        StrategyId.DIRECT_RETRY,
        StrategyId.BUMPSHIELD,
        StrategyId.DIRECT_RETRY,
        StrategyId.BUMPSHIELD,
        StrategyId.DIRECT_ONE_SHOT,
    ]


def test_global_provider_failure_pauses_and_resume_continues_unexecuted(
    tmp_path: Path,
) -> None:
    cases = tuple(_case(tmp_path, f"case-{index}") for index in range(3))
    suite = BenchmarkSuite(
        "suite",
        cases,
        (StrategyId.DIRECT_ONE_SHOT, StrategyId.BUMPSHIELD),
    )
    direct = FakeStrategy(StrategyId.DIRECT_ONE_SHOT)
    direct.maximum_provider_calls = 1
    quota = ProviderQuotaStrategy(StrategyId.BUMPSHIELD)
    config = BumpShieldConfig(
        state_root=tmp_path / "state", repair_provider_executable=sys.executable
    )
    first_runner = BenchmarkRunner(
        config,
        validator=FakeValidator(),
        strategies={
            StrategyId.DIRECT_ONE_SHOT: direct,
            StrategyId.BUMPSHIELD: quota,
        },
    )

    paused = first_runner.run(suite)

    assert paused.status is BenchmarkRunStatus.PAUSED_PROVIDER_UNAVAILABLE
    assert paused.completed_trials == 2
    assert paused.unexecuted_trials == 4
    assert quota.calls == 1
    quota_result = next(
        item for item in paused.results if item.strategy is StrategyId.BUMPSHIELD
    )
    assert quota_result.provider_failure_kind is ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED

    recovered = FakeStrategy(StrategyId.BUMPSHIELD)
    second_runner = BenchmarkRunner(
        config,
        validator=FakeValidator(),
        strategies={
            StrategyId.DIRECT_ONE_SHOT: direct,
            StrategyId.BUMPSHIELD: recovered,
        },
    )
    completed = second_runner.run(
        suite, resume_run_id=paused.benchmark_run_id
    )

    assert completed.status is BenchmarkRunStatus.COMPLETED
    assert completed.completed_trials == 6
    assert completed.unexecuted_trials == 0
    assert recovered.calls == 2
    persisted_quota = next(
        item
        for item in completed.results
        if item.case_id == "case-0" and item.strategy is StrategyId.BUMPSHIELD
    )
    assert persisted_quota.provider_failure_kind is ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED
