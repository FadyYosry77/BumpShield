from dataclasses import replace
from pathlib import Path

from bumpshield.agent.repair_engine import RepairEngine
from bumpshield.agent.repairer import MigrationPlanner, RepairContextBuilder
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import (
    CommandResult,
    DependencyTreeCommandResult,
    DependencyUpgrade,
    ExecutionResult,
    ExecutionStatus,
    MigrationPlanningResult,
    MigrationStatus,
    PlanStatus,
    RepairProviderResult,
    RepairProviderStatus,
    TaskSpec,
)
from test_planner import _location, _planning_inputs
from test_reproducer import run_git


def _repository(path: Path) -> tuple[str, str]:
    runner = CommandRunner(default_timeout=5)
    path.mkdir()
    run_git(runner, path, "init", "--quiet")
    run_git(runner, path, "config", "user.name", "BumpShield Tests")
    run_git(runner, path, "config", "user.email", "tests@example.invalid")
    source = path / "src/main/java/com/example/Foo.java"
    test = path / "src/test/java/com/example/FooTest.java"
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    source.write_text("class Foo {}\n", encoding="utf-8")
    test.write_text("class FooTest {}\n", encoding="utf-8")
    (path / "pom.xml").write_text("<project/>\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "base")
    base = run_git(runner, path, "rev-parse", "HEAD")
    source.write_text(
        "class Foo { Object value(Parser p, String x) { return p.parseValue(x); } }\n",
        encoding="utf-8",
    )
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "updated")
    updated = run_git(runner, path, "rev-parse", "HEAD")
    return base, updated


def _task(path: Path, base: str, updated: str) -> TaskSpec:
    return TaskSpec(
        path,
        base,
        updated,
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
    )


def _planning(task: TaskSpec, run_directory: Path) -> MigrationPlanningResult:
    bundle, diagnosis = _planning_inputs()
    bundle = replace(
        bundle,
        task=task,
        artifact_directory=run_directory,
        run_id="repair-run",
    )
    diagnosis = replace(
        diagnosis,
        run_id="repair-run",
        artifact_directory=run_directory,
    )
    plan = MigrationPlanner().plan(bundle, diagnosis, (_location(line=1),))
    context = RepairContextBuilder().build(None, bundle, diagnosis, plan)
    return MigrationPlanningResult(task, bundle, diagnosis, plan, context)


class FakePlanning:
    def __init__(self, result: MigrationPlanningResult) -> None:
        self.result = result

    def plan(self, task: TaskSpec, run_id=None) -> MigrationPlanningResult:
        assert task == self.result.task
        return self.result


class FakeProvider:
    def __init__(self, edits) -> None:
        self.edits = list(edits)
        self.requests = []
        self.starting_sources = []

    def repair(self, workspace, request):
        self.requests.append(request)
        source = workspace.path / "src/main/java/com/example/Foo.java"
        self.starting_sources.append(source.read_text(encoding="utf-8"))
        edit = self.edits[len(self.requests) - 1]
        edit(workspace.path)
        return RepairProviderResult(
            RepairProviderStatus.SUCCESS,
            "fake",
            "Everything is fixed and all tests pass.",
            "Everything is fixed and all tests pass.",
            0.01,
        )


class FakeMaven:
    def __init__(self, compile_statuses, test_statuses=()) -> None:
        self.compile_statuses = list(compile_statuses)
        self.test_statuses = list(test_statuses)
        self.lifecycle_calls = []
        self.tree = """org.example:app:jar:1.0
+- org.example:core:jar:2.0:compile
\\- org.example:parser:jar:5.0:compile
"""

    def dependency_tree(self, workspace, output_file):
        output_file.write_text(self.tree, encoding="utf-8")
        return DependencyTreeCommandResult(
            _execution(ExecutionStatus.PASS, workspace.path, "dependency:tree"),
            output_file,
            self.tree,
        )

    def execute_lifecycle(self, workspace, goal):
        self.lifecycle_calls.append((workspace.path, goal))
        statuses = self.compile_statuses if goal == "compile" else self.test_statuses
        return _execution(statuses.pop(0), workspace.path, goal)


def _execution(status: ExecutionStatus, cwd: Path, goal: str) -> ExecutionResult:
    output = ""
    if status is ExecutionStatus.FAIL:
        output = (
            "[ERROR] src/main/java/com/example/Foo.java:[1,20] cannot find symbol\n"
            "[ERROR] symbol: class ParserOptions\n"
        )
    command = CommandResult(
        ("mvn", "-B", goal),
        cwd,
        0 if status is ExecutionStatus.PASS else 1,
        output,
        "",
        0.1,
        status is ExecutionStatus.TIMEOUT,
    )
    return ExecutionResult(status, (command,))


def _replace_source(text: str):
    def edit(root: Path) -> None:
        (root / "src/main/java/com/example/Foo.java").write_text(
            text, encoding="utf-8"
        )

    return edit


def test_failed_first_attempt_then_verified_second_attempt(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    base, updated = _repository(repository)
    task = _task(repository, base, updated)
    run_directory = tmp_path / "state/runs/repair-run"
    run_directory.mkdir(parents=True)
    planning = _planning(task, run_directory)
    provider = FakeProvider(
        [
            _replace_source("class Foo { ParserOptions broken; }\n"),
            _replace_source("class Foo { Object value() { return new Object(); } }\n"),
        ]
    )
    maven = FakeMaven(
        [ExecutionStatus.FAIL, ExecutionStatus.PASS],
        [ExecutionStatus.PASS],
    )

    result = RepairEngine(
        planning=FakePlanning(planning),
        provider=provider,
        maven=maven,
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).repair(task)

    assert result.status is MigrationStatus.VERIFIED_MIGRATION
    assert len(result.attempts) == 2
    assert result.winning_attempt == 2
    assert provider.requests[0].feedback is None
    assert provider.requests[1].feedback is not None
    assert "ParserOptions" in provider.requests[1].feedback.bounded_excerpt
    assert provider.starting_sources[0] == provider.starting_sources[1]
    assert (run_directory / "attempts/1/patch.diff").is_file()
    assert (run_directory / "attempts/2/patch.diff").is_file()
    assert (run_directory / "attempts/1/feedback.json").is_file()
    assert (run_directory / "final.patch").read_text() == (
        run_directory / "attempts/2/patch.diff"
    ).read_text()
    assert (run_directory / "repair-result.json").is_file()
    assert (run_directory / "migration-report.txt").is_file()
    assert "parseValue" in (
        repository / "src/main/java/com/example/Foo.java"
    ).read_text()


def test_attempt_limit_and_provider_claim_cannot_self_verify(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    base, updated = _repository(repository)
    task = _task(repository, base, updated)
    run_directory = tmp_path / "state/runs/repair-run"
    run_directory.mkdir(parents=True)
    planning = _planning(task, run_directory)
    provider = FakeProvider(
        [_replace_source(f"class Foo {{ int n = {index}; }}\n") for index in range(3)]
    )
    maven = FakeMaven([ExecutionStatus.FAIL] * 3)

    result = RepairEngine(
        planning=FakePlanning(planning),
        provider=provider,
        maven=maven,
        config=BumpShieldConfig(
            state_root=tmp_path / "state", max_repair_attempts=3
        ),
    ).repair(task)

    assert result.status is MigrationStatus.UNRESOLVED
    assert len(result.attempts) == 3
    assert len(provider.requests) == 3
    assert result.winning_attempt is None


def test_no_changes_retries_only_to_configured_limit(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    base, updated = _repository(repository)
    task = _task(repository, base, updated)
    run_directory = tmp_path / "state/runs/repair-run"
    run_directory.mkdir(parents=True)
    planning = _planning(task, run_directory)
    provider = FakeProvider([lambda _: None, lambda _: None])
    maven = FakeMaven([])

    result = RepairEngine(
        planning=FakePlanning(planning),
        provider=provider,
        maven=maven,
        config=BumpShieldConfig(
            state_root=tmp_path / "state", max_repair_attempts=2
        ),
    ).repair(task)

    assert result.status is MigrationStatus.UNRESOLVED
    assert [attempt.status.value for attempt in result.attempts] == [
        "NO_CHANGES",
        "NO_CHANGES",
    ]
    assert len(provider.requests) == 2
    assert not maven.lifecycle_calls


def test_non_actionable_plan_never_invokes_provider(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    base, updated = _repository(repository)
    task = _task(repository, base, updated)
    run_directory = tmp_path / "state/runs/repair-run"
    run_directory.mkdir(parents=True)
    planning = _planning(task, run_directory)
    blocked_plan = replace(planning.plan, status=PlanStatus.NEEDS_HUMAN_REVIEW)
    planning = replace(
        planning,
        plan=blocked_plan,
        repair_context=replace(planning.repair_context, plan=blocked_plan),
    )
    provider = FakeProvider([])

    result = RepairEngine(
        planning=FakePlanning(planning),
        provider=provider,
        maven=FakeMaven([]),
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).repair(task)

    assert result.status is MigrationStatus.NEEDS_HUMAN_REVIEW
    assert not result.attempts
    assert not provider.requests


def test_dependency_downgrade_stops_before_green_commands(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    base, updated = _repository(repository)
    task = _task(repository, base, updated)
    run_directory = tmp_path / "state/runs/repair-run"
    run_directory.mkdir(parents=True)
    planning = _planning(task, run_directory)
    provider = FakeProvider([_replace_source("class Foo { }\n")])
    maven = FakeMaven([ExecutionStatus.PASS], [ExecutionStatus.PASS])
    maven.tree = """org.example:app:jar:1.0
+- org.example:core:jar:1.0:compile
\\- org.example:parser:jar:4.0:compile
"""

    result = RepairEngine(
        planning=FakePlanning(planning),
        provider=provider,
        maven=maven,
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).repair(task)

    assert result.status is MigrationStatus.UNRESOLVED
    assert result.attempts[0].status.value == "PATCH_REJECTED"
    assert not maven.lifecycle_calls


def test_original_repository_status_and_contents_remain_identical(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    base, updated = _repository(repository)
    task = _task(repository, base, updated)
    runner = CommandRunner()
    (repository / "src/test/java/com/example/FooTest.java").write_text(
        "class FooTest { int staged = 1; }\n", encoding="utf-8"
    )
    run_git(runner, repository, "add", "src/test/java/com/example/FooTest.java")
    (repository / "src/main/java/com/example/Foo.java").write_text(
        "class Foo { int unstaged = 1; }\n", encoding="utf-8"
    )
    (repository / "notes.txt").write_text("untracked\n", encoding="utf-8")
    before_head = run_git(runner, repository, "rev-parse", "HEAD")
    before_status = run_git(runner, repository, "status", "--porcelain=v1")
    before_files = {
        path.relative_to(repository): path.read_bytes()
        for path in repository.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    run_directory = tmp_path / "state/runs/repair-run"
    run_directory.mkdir(parents=True)
    planning = _planning(task, run_directory)

    RepairEngine(
        planning=FakePlanning(planning),
        provider=FakeProvider([_replace_source("class Foo { }\n")]),
        maven=FakeMaven([ExecutionStatus.PASS], [ExecutionStatus.PASS]),
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).repair(task)

    after_files = {
        path.relative_to(repository): path.read_bytes()
        for path in repository.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    assert run_git(runner, repository, "rev-parse", "HEAD") == before_head
    assert run_git(runner, repository, "status", "--porcelain=v1") == before_status
    assert after_files == before_files
    assert not (repository / ".bumpshield").exists()
