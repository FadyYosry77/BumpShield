from pathlib import Path

from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseType,
    BenchmarkSource,
    BenchmarkSuite,
    StrategyId,
)
from bumpshield.evaluation.schedule import counterbalanced_schedule
from bumpshield.models import DependencyUpgrade, TaskSpec


def _case(tmp_path: Path, case_id: str) -> BenchmarkCase:
    repository = tmp_path / case_id
    repository.mkdir()
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


def test_three_strategy_schedule_rotates_by_case_deterministically(tmp_path: Path) -> None:
    strategies = (
        StrategyId.DIRECT_ONE_SHOT,
        StrategyId.DIRECT_RETRY,
        StrategyId.BUMPSHIELD,
    )
    suite = BenchmarkSuite(
        "suite", tuple(_case(tmp_path, f"case-{n}") for n in range(4)), strategies
    )

    first = counterbalanced_schedule(suite)
    second = counterbalanced_schedule(suite)

    assert first == second
    assert [item.strategy for item in first[:3]] == list(strategies)
    assert [item.strategy for item in first[3:6]] == [
        StrategyId.DIRECT_RETRY,
        StrategyId.BUMPSHIELD,
        StrategyId.DIRECT_ONE_SHOT,
    ]
    assert [item.strategy for item in first[6:9]] == [
        StrategyId.BUMPSHIELD,
        StrategyId.DIRECT_ONE_SHOT,
        StrategyId.DIRECT_RETRY,
    ]
    assert [item.execution_position for item in first] == [1, 2, 3] * 4


def test_trial_index_also_rotates_order(tmp_path: Path) -> None:
    strategies = (StrategyId.DIRECT_ONE_SHOT, StrategyId.BUMPSHIELD)
    suite = BenchmarkSuite(
        "suite", (_case(tmp_path, "case"),), strategies, trials=2
    )
    schedule = counterbalanced_schedule(suite)

    assert [item.strategy for item in schedule[:2]] == list(strategies)
    assert [item.strategy for item in schedule[2:]] == list(reversed(strategies))
    assert [item.execution_position for item in schedule] == [1, 2, 1, 2]
