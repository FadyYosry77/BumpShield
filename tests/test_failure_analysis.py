from __future__ import annotations

import json
from pathlib import Path

import pytest

from bumpshield.analysis.failure_parser import (
    FailureAnalysisError,
    FailureAnalyzer,
    FailureArtifacts,
    classify_failure_analysis,
)
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import (
    CommandResult,
    DependencyUpgrade,
    ExecutionResult,
    ExecutionStatus,
    FailureAnalysisResult,
    FailureAnalysisStatus,
    FailureCategory,
    FailureSignal,
    TaskSpec,
)
from bumpshield.repo.workspace import RepositoryWorkspace


JAVA_SOURCE = """\
package com.example;

import org.example.Parser;

class Foo {
    Object parse(Parser parser) { return parser.missing(); }
}
"""


def run_git(runner: CommandRunner, cwd: Path, *arguments: str) -> str:
    result = runner.run(["git", *arguments], cwd=cwd, timeout=5)
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def create_repository(path: Path) -> tuple[str, str]:
    runner = CommandRunner(default_timeout=5)
    path.mkdir()
    run_git(runner, path, "init", "--quiet")
    run_git(runner, path, "config", "user.name", "BumpShield Tests")
    run_git(runner, path, "config", "user.email", "tests@example.invalid")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "base")
    base = run_git(runner, path, "rev-parse", "HEAD")
    source = path / "src/main/java/com/example/Foo.java"
    source.parent.mkdir(parents=True)
    source.write_text(JAVA_SOURCE, encoding="utf-8")
    (path / "updated.txt").write_text("updated\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "updated")
    updated = run_git(runner, path, "rev-parse", "HEAD")
    return base, updated


def make_task(repository: Path, base: str, updated: str) -> TaskSpec:
    return TaskSpec(
        repository=repository,
        base_commit=base,
        updated_commit=updated,
        target_dependency=DependencyUpgrade(
            group_id="org.example",
            artifact_id="parser",
            old_version="1.0",
            new_version="2.0",
        ),
    )


class FixtureMaven:
    def __init__(
        self,
        status: ExecutionStatus = ExecutionStatus.FAIL,
        *,
        structured_output: bool = True,
    ) -> None:
        self.status = status
        self.structured_output = structured_output
        self.calls: list[Path] = []

    def execute(self, workspace: RepositoryWorkspace) -> ExecutionResult:
        self.calls.append(workspace.path)
        if self.status is ExecutionStatus.ERROR:
            return ExecutionResult(
                status=ExecutionStatus.ERROR,
                detail="mvn missing",
            )
        if self.structured_output:
            source = workspace.path / "src/main/java/com/example/Foo.java"
            stdout = (
                f"[ERROR] {source}:[6,48] cannot find symbol\n"
                "[ERROR] symbol: method missing()\n"
                "[ERROR] location: variable parser of type org.example.Parser\n"
            )
        else:
            stdout = "[ERROR] Failed to execute goal with unknown project failure\n"
        command = CommandResult(
            command=("./mvnw", "-B", "test"),
            cwd=workspace.path,
            exit_code=(
                0
                if self.status is ExecutionStatus.PASS
                else None
                if self.status is ExecutionStatus.TIMEOUT
                else 1
            ),
            stdout=stdout,
            stderr="stderr evidence\n",
            duration_seconds=0.4,
            timed_out=self.status is ExecutionStatus.TIMEOUT,
        )
        return ExecutionResult(status=self.status, commands=(command,))


def test_failure_analysis_localizes_updated_revision_and_persists_artifacts(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    base, updated = create_repository(repository)
    state_root = tmp_path / "state"
    maven = FixtureMaven()

    result = FailureAnalyzer(
        maven=maven,
        config=BumpShieldConfig(state_root=state_root),
    ).analyze(make_task(repository, base, updated), run_id="failure-run")

    artifact_path = state_root / "runs" / "failure-run"
    assert result.status is FailureAnalysisStatus.FAILURES_LOCALIZED
    assert result.primary_failure is not None
    assert result.primary_failure.category is FailureCategory.MISSING_SYMBOL
    assert result.primary_failure.file == Path("src/main/java/com/example/Foo.java")
    assert result.primary_failure.line == 6
    assert result.source_contexts[0].package == "com.example"
    assert result.source_contexts[0].imports == ("org.example.Parser",)
    assert all(not workspace.exists() for workspace in maven.calls)
    assert result.artifact_directory == artifact_path
    assert {path.name for path in artifact_path.iterdir()} == {
        "task.json",
        "updated-build.log",
        "failures.json",
        "source-contexts.json",
        "failure-analysis.json",
    }
    persisted_task = json.loads((artifact_path / "task.json").read_text())
    assert persisted_task["repository"] == str(repository)
    build_log = (artifact_path / "updated-build.log").read_text()
    assert "[stdout]" in build_log and "[stderr]" in build_log
    persisted_failure = json.loads((artifact_path / "failures.json").read_text())[0]
    assert persisted_failure["file"] == "src/main/java/com/example/Foo.java"
    assert persisted_failure["symbol"] == "missing()"
    persisted_context = json.loads(
        (artifact_path / "source-contexts.json").read_text()
    )[0]
    assert persisted_context["focus_line"] == 6
    summary = json.loads((artifact_path / "failure-analysis.json").read_text())
    assert summary["status"] == "FAILURES_LOCALIZED"
    assert summary["localized_count"] == 1
    assert not (repository / ".bumpshield").exists()


@pytest.mark.parametrize(
    ("execution_status", "expected_analysis"),
    [
        (ExecutionStatus.PASS, FailureAnalysisStatus.NO_FAILURE),
        (ExecutionStatus.TIMEOUT, FailureAnalysisStatus.TIMEOUT),
        (ExecutionStatus.ERROR, FailureAnalysisStatus.EXECUTION_ERROR),
    ],
)
def test_non_failure_and_infrastructure_statuses_remain_distinct(
    tmp_path: Path,
    execution_status: ExecutionStatus,
    expected_analysis: FailureAnalysisStatus,
) -> None:
    repository = tmp_path / "repository"
    base, updated = create_repository(repository)

    result = FailureAnalyzer(
        maven=FixtureMaven(execution_status),
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).analyze(make_task(repository, base, updated), run_id="status-run")

    assert result.status is expected_analysis
    assert result.failures == ()
    assert result.source_contexts == ()


def test_build_failure_without_structured_signal_is_not_no_failure(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    base, updated = create_repository(repository)

    result = FailureAnalyzer(
        maven=FixtureMaven(structured_output=False),
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).analyze(make_task(repository, base, updated), run_id="unparsed-run")

    assert result.execution.status is ExecutionStatus.FAIL
    assert result.status is FailureAnalysisStatus.FAILURE_UNLOCALIZED
    assert result.failures == ()


def test_partial_status_requires_some_but_not_all_failures_localized() -> None:
    execution = ExecutionResult(status=ExecutionStatus.FAIL)
    localized = FailureSignal(
        category=FailureCategory.MISSING_SYMBOL,
        message="cannot find symbol",
        file=Path("src/main/java/Foo.java"),
    )
    unlocalized = FailureSignal(
        category=FailureCategory.TEST_FAILURE,
        message="tests failed",
    )

    status = classify_failure_analysis(execution, (localized, unlocalized))

    assert status is FailureAnalysisStatus.FAILURES_PARSED_PARTIALLY


def test_primary_failure_prefers_localized_compiler_over_earlier_test_summary(
    tmp_path: Path,
) -> None:
    test_summary = FailureSignal(
        category=FailureCategory.TEST_FAILURE,
        message="tests failed",
    )
    compiler = FailureSignal(
        category=FailureCategory.MISSING_SYMBOL,
        message="cannot find symbol",
        file=Path("src/main/java/Foo.java"),
        line=8,
    )
    task = TaskSpec(
        repository=tmp_path,
        base_commit="base",
        updated_commit="updated",
        target_dependency=DependencyUpgrade("g", "a", "1", "2"),
    )
    result = FailureAnalysisResult(
        run_id="primary-run",
        task=task,
        artifact_directory=tmp_path / "state",
        status=FailureAnalysisStatus.FAILURES_PARSED_PARTIALLY,
        execution=ExecutionResult(status=ExecutionStatus.FAIL),
        failures=(test_summary, compiler),
    )

    assert result.primary_failure is compiler


def test_failure_analysis_leaves_complete_repository_state_unchanged(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    base, updated = create_repository(repository)
    (repository / "tracked.txt").write_text("unstaged user edit\n", encoding="utf-8")
    (repository / "updated.txt").write_text("staged user edit\n", encoding="utf-8")
    (repository / "user-notes.txt").write_text("existing untracked\n", encoding="utf-8")
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "add", "updated.txt")
    status_before = run_git(runner, repository, "status", "--porcelain=v1")
    head_before = run_git(runner, repository, "rev-parse", "HEAD")
    index_before = run_git(runner, repository, "diff", "--cached", "--binary")

    FailureAnalyzer(
        maven=FixtureMaven(),
        config=BumpShieldConfig(state_root=tmp_path / "external-state"),
    ).analyze(make_task(repository, base, updated), run_id="isolation-run")

    assert run_git(runner, repository, "status", "--porcelain=v1") == status_before
    assert run_git(runner, repository, "rev-parse", "HEAD") == head_before
    assert run_git(runner, repository, "diff", "--cached", "--binary") == index_before
    assert (repository / "tracked.txt").read_text() == "unstaged user edit\n"
    assert (repository / "updated.txt").read_text() == "staged user edit\n"
    assert (repository / "user-notes.txt").read_text() == "existing untracked\n"
    assert not (repository / ".bumpshield").exists()


def test_state_inside_repository_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base, updated = create_repository(repository)

    with pytest.raises(FailureAnalysisError, match="outside analyzed repository"):
        FailureAnalyzer(
            maven=FixtureMaven(),
            config=BumpShieldConfig(state_root=repository / "state"),
        ).analyze(make_task(repository, base, updated), run_id="unsafe-run")

    assert not (repository / "state").exists()


def test_artifact_failure_still_cleans_updated_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    base, updated = create_repository(repository)

    def fail_write(
        artifacts: FailureArtifacts,
        failures: tuple[FailureSignal, ...],
    ) -> None:
        raise FailureAnalysisError("artifact write failed")

    monkeypatch.setattr(FailureArtifacts, "write_failures", fail_write)

    with pytest.raises(FailureAnalysisError, match="artifact write failed"):
        FailureAnalyzer(
            maven=FixtureMaven(),
            config=BumpShieldConfig(state_root=tmp_path / "state"),
        ).analyze(make_task(repository, base, updated), run_id="artifact-failure-run")

    worktrees = run_git(
        CommandRunner(default_timeout=5),
        repository,
        "worktree",
        "list",
        "--porcelain",
    )
    assert worktrees.count("worktree ") == 1
