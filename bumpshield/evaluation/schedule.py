"""Deterministic counterbalanced benchmark scheduling."""

from __future__ import annotations

from bumpshield.evaluation.models import BenchmarkSuite, ScheduleEntry


SCHEDULING_POLICY_VERSION = "counterbalanced-rotation-v1"


def counterbalanced_schedule(suite: BenchmarkSuite) -> tuple[ScheduleEntry, ...]:
    """Rotate strategy order by case and trial without randomness."""
    entries: list[ScheduleEntry] = []
    strategies = suite.strategies
    for case_index, case in enumerate(suite.cases):
        for trial in range(1, suite.trials + 1):
            offset = (case_index + trial - 1) % len(strategies)
            rotated = strategies[offset:] + strategies[:offset]
            for position, strategy in enumerate(rotated, start=1):
                entries.append(
                    ScheduleEntry(case.id, trial, strategy, position)
                )
    return tuple(entries)
