from pathlib import Path

from bumpshield.agent.provider import build_repair_request
from bumpshield.config import BumpShieldConfig
from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseType,
    BenchmarkGroundTruth,
    BenchmarkSource,
    GroundTruthDependency,
)
from bumpshield.evaluation.strategies import (
    DirectBaselinePlanning,
    DirectRetryStrategy,
    TimedPlanning,
)
from bumpshield.models import (
    CommandResult,
    DependencyUpgrade,
    ExecutionResult,
    ExecutionStatus,
    FailureAnalysisResult,
    FailureAnalysisStatus,
    FailureCategory,
    FailureSignal,
    MigrationKind,
    RepairAttemptStatus,
    RepairFeedback,
    SourceContext,
    SourceLine,
    TaskSpec,
)


class FakeFailureAnalyzer:
    def __init__(self, result: FailureAnalysisResult) -> None:
        self.result = result

    def analyze(self, task, run_id=None):
        assert task == self.result.task
        return self.result


def _case(tmp_path: Path) -> tuple[BenchmarkCase, FailureAnalysisResult]:
    repository = tmp_path / "repo"
    repository.mkdir()
    task = TaskSpec(
        repository,
        "base",
        "updated",
        DependencyUpgrade("org.example", "core-lib", "1", "2"),
    )
    command = CommandResult(
        ("mvn", "-B", "test"),
        repository,
        1,
        "cannot find symbol",
        "",
        1,
    )
    execution = ExecutionResult(ExecutionStatus.FAIL, (command,))
    signal = FailureSignal(
        FailureCategory.MISSING_SYMBOL,
        "cannot find symbol method parseValue",
        Path("src/main/java/example/Foo.java"),
        3,
        symbol="parseValue(java.lang.String)",
    )
    context = SourceContext(
        Path("src/main/java/example/Foo.java"),
        1,
        3,
        3,
        (
            SourceLine(1, "class Foo {"),
            SourceLine(2, "  Parser parser;"),
            SourceLine(3, "  String run(String x) { return parser.parseValue(x); }"),
        ),
    )
    run_directory = tmp_path / "state/runs/failure-run"
    run_directory.mkdir(parents=True)
    failure = FailureAnalysisResult(
        "failure-run",
        task,
        run_directory,
        FailureAnalysisStatus.FAILURES_LOCALIZED,
        execution,
        (signal,),
        (context,),
    )
    case = BenchmarkCase(
        "transitive-case",
        "ground truth must stay evaluation-only",
        task,
        BenchmarkCaseType.TRANSITIVE,
        BenchmarkSource.SYNTHETIC_FIXTURE,
        ground_truth=BenchmarkGroundTruth(
            GroundTruthDependency("org.example", "secret-parser", "4", "5"),
            MigrationKind.REMOVED_METHOD,
            "org.example.SecretParser",
            "secretMethod(java.lang.String)",
        ),
    )
    return case, failure


def test_direct_one_shot_prompt_contains_failure_but_no_ground_truth(tmp_path: Path) -> None:
    case, failure = _case(tmp_path)
    service = DirectBaselinePlanning(
        BumpShieldConfig(state_root=tmp_path / "state"),
        failure_analyzer=FakeFailureAnalyzer(failure),
    )

    planning = service.plan(case.task)
    request = build_repair_request(planning.repair_context, 1, None)

    assert "core-lib:2" in request.instruction
    assert "cannot find symbol method parseValue" in request.instruction
    assert "src/main/java/example/Foo.java" in request.instruction
    assert "secret-parser" not in request.instruction
    assert "SecretParser" not in request.instruction
    assert "secretMethod" not in request.instruction
    assert "Observed new API candidates" not in request.instruction
    assert planning.evidence.dependency_diff.changes == ()
    assert planning.evidence.api_evidence == ()
    assert planning.diagnosis.hypotheses == ()


def test_timed_planning_delegates_and_records_duration(tmp_path: Path) -> None:
    case, failure = _case(tmp_path)
    delegate = DirectBaselinePlanning(
        BumpShieldConfig(state_root=tmp_path / "state"),
        failure_analyzer=FakeFailureAnalyzer(failure),
    )
    timed = TimedPlanning(delegate)

    result = timed.plan(case.task)

    assert result.task == case.task
    assert timed.duration_seconds is not None
    assert timed.duration_seconds >= 0


def test_direct_retry_matches_attempt_budget_and_never_leaks_ground_truth(
    tmp_path: Path,
) -> None:
    case, failure = _case(tmp_path)
    config = BumpShieldConfig(state_root=tmp_path / "state", max_repair_attempts=3)
    strategy = DirectRetryStrategy(config)
    service = DirectBaselinePlanning(
        config,
        failure_analyzer=FakeFailureAnalyzer(failure),
        strategy_id=strategy.id,
    )
    planning = service.plan(case.task)
    feedback = RepairFeedback(
        1,
        RepairAttemptStatus.COMPILE_FAILED,
        (Path("src/main/java/example/Foo.java"),),
        "previous compile failed",
        bounded_excerpt="cannot resolve Options",
    )

    requests = (
        build_repair_request(planning.repair_context, 1, None),
        build_repair_request(planning.repair_context, 2, feedback),
        build_repair_request(planning.repair_context, 3, feedback),
    )

    assert strategy.maximum_provider_calls == 3
    for request in requests:
        assert "secret-parser" not in request.instruction
        assert "SecretParser" not in request.instruction
        assert "secretMethod" not in request.instruction
        assert "Observed new API candidates" not in request.instruction
    assert planning.evidence.dependency_diff.changes == ()
    assert planning.evidence.api_evidence == ()
    assert planning.diagnosis.hypotheses == ()


def test_direct_retry_preserves_naturally_observed_feedback(tmp_path: Path) -> None:
    case, failure = _case(tmp_path)
    service = DirectBaselinePlanning(
        BumpShieldConfig(state_root=tmp_path / "state"),
        failure_analyzer=FakeFailureAnalyzer(failure),
    )
    planning = service.plan(case.task)
    feedback = RepairFeedback(
        1,
        RepairAttemptStatus.COMPILE_FAILED,
        (),
        "compiler named secret-parser",
        bounded_excerpt="secret-parser was emitted by actual build output",
    )

    request = build_repair_request(planning.repair_context, 2, feedback)

    assert "secret-parser" in request.instruction
