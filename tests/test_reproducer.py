from __future__ import annotations

import json
from pathlib import Path

import pytest

from bumpshield.analysis.reproducer import (
    RegressionReproducer,
    ReproductionArtifacts,
    ReproductionError,
    classify_reproduction,
    generate_run_id,
)
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import (
    CommandResult,
    DependencyUpgrade,
    ExecutionResult,
    ExecutionStatus,
    ReproductionStatus,
    TaskSpec,
)
from bumpshield.repo.workspace import RepositoryWorkspace


def run_git(runner: CommandRunner, cwd: Path, *arguments: str) -> str:
    result = runner.run(["git", *arguments], cwd=cwd, timeout=5)
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def create_marker_repository(
    path: Path,
    *,
    base_status: ExecutionStatus = ExecutionStatus.PASS,
    updated_status: ExecutionStatus = ExecutionStatus.FAIL,
) -> tuple[str, str]:
    runner = CommandRunner(default_timeout=5)
    path.mkdir()
    run_git(runner, path, "init", "--quiet")
    run_git(runner, path, "config", "user.name", "BumpShield Tests")
    run_git(runner, path, "config", "user.email", "tests@example.invalid")
    (path / "build-status.txt").write_text(base_status.value, encoding="utf-8")
    (path / "tracked.txt").write_text("committed\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "base")
    base_commit = run_git(runner, path, "rev-parse", "HEAD")
    (path / "build-status.txt").write_text(updated_status.value, encoding="utf-8")
    (path / "revision.txt").write_text("updated\n", encoding="utf-8")
    run_git(runner, path, "add", "build-status.txt", "revision.txt")
    run_git(runner, path, "commit", "--quiet", "-m", "updated")
    updated_commit = run_git(runner, path, "rev-parse", "HEAD")
    return base_commit, updated_commit


def task(path: Path, base_commit: str, updated_commit: str) -> TaskSpec:
    return TaskSpec(
        repository=path,
        base_commit=base_commit,
        updated_commit=updated_commit,
        target_dependency=DependencyUpgrade(
            group_id="org.example",
            artifact_id="foo",
            old_version="1.0",
            new_version="2.0",
        ),
    )


class MarkerMavenExecutor:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def execute(self, workspace: RepositoryWorkspace) -> ExecutionResult:
        path = workspace.path
        self.calls.append(path)
        status = ExecutionStatus((path / "build-status.txt").read_text(encoding="utf-8"))
        command = CommandResult(
            command=("./mvnw", "-B", "test"),
            cwd=path,
            exit_code=(
                0
                if status is ExecutionStatus.PASS
                else None
                if status is ExecutionStatus.TIMEOUT
                else 1
            ),
            stdout=f"{status.value} output\n",
            stderr="failure details\n" if status is ExecutionStatus.FAIL else "",
            duration_seconds=0.1,
            timed_out=status is ExecutionStatus.TIMEOUT,
        )
        return ExecutionResult(status=status, commands=(command,))


def reproducer(state_root: Path, maven: MarkerMavenExecutor) -> RegressionReproducer:
    return RegressionReproducer(
        maven=maven,
        config=BumpShieldConfig(state_root=state_root),
    )


def test_reproducer_confirms_regression_and_persists_artifacts(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base_commit, updated_commit = create_marker_repository(repository)
    (repository / "tracked.txt").write_text("uncommitted\n", encoding="utf-8")
    original_head = run_git(CommandRunner(), repository, "rev-parse", "HEAD")
    maven = MarkerMavenExecutor()

    state_root = tmp_path / "state"
    result = reproducer(state_root, maven).reproduce(
        task(repository, base_commit, updated_commit),
        run_id="confirmed-run",
    )

    assert result.status is ReproductionStatus.CONFIRMED
    assert len(maven.calls) == 2
    assert all(not path.exists() for path in maven.calls)
    assert run_git(CommandRunner(), repository, "rev-parse", "HEAD") == original_head
    assert (repository / "tracked.txt").read_text(encoding="utf-8") == "uncommitted\n"
    assert result.artifact_directory == state_root / "runs" / "confirmed-run"
    assert not (repository / ".bumpshield").exists()
    assert (result.artifact_directory / "task.json").is_file()
    persisted_task = json.loads((result.artifact_directory / "task.json").read_text())
    assert persisted_task["repository"] == str(repository)
    assert persisted_task["base_commit"] == base_commit
    assert persisted_task["updated_commit"] == updated_commit
    assert "PASS output" in (result.artifact_directory / "base-build.log").read_text()
    assert "failure details" in (result.artifact_directory / "updated-build.log").read_text()
    persisted = json.loads((result.artifact_directory / "reproduction.json").read_text())
    assert persisted["status"] == "CONFIRMED"
    assert persisted["base"]["exit_code"] == 0
    assert persisted["updated"]["exit_code"] == 1


def test_reproducer_stops_after_base_failure(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base_commit, updated_commit = create_marker_repository(
        repository,
        base_status=ExecutionStatus.FAIL,
    )
    maven = MarkerMavenExecutor()

    result = reproducer(tmp_path / "state", maven).reproduce(
        task(repository, base_commit, updated_commit),
        run_id="base-failed-run",
    )

    assert result.status is ReproductionStatus.BASE_FAILED
    assert result.updated is None
    assert len(maven.calls) == 1
    assert not (result.artifact_directory / "updated-build.log").exists()


def test_reproducer_classifies_updated_pass(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base_commit, updated_commit = create_marker_repository(
        repository,
        updated_status=ExecutionStatus.PASS,
    )

    result = reproducer(tmp_path / "state", MarkerMavenExecutor()).reproduce(
        task(repository, base_commit, updated_commit),
        run_id="updated-passed-run",
    )

    assert result.status is ReproductionStatus.UPDATED_PASSED


def test_updated_timeout_is_persisted_and_workspaces_are_cleaned(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base_commit, updated_commit = create_marker_repository(
        repository,
        updated_status=ExecutionStatus.TIMEOUT,
    )
    maven = MarkerMavenExecutor()

    result = reproducer(tmp_path / "state", maven).reproduce(
        task(repository, base_commit, updated_commit),
        run_id="updated-timeout-run",
    )

    assert result.status is ReproductionStatus.EXECUTION_ERROR
    assert result.updated is not None
    assert result.updated.execution.status is ExecutionStatus.TIMEOUT
    assert all(not path.exists() for path in maven.calls)
    persisted = json.loads((result.artifact_directory / "reproduction.json").read_text())
    assert persisted["updated"]["timed_out"] is True


def test_artifact_failure_still_cleans_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    base_commit, updated_commit = create_marker_repository(repository)

    def fail_log_write(
        artifacts: ReproductionArtifacts,
        revision: str,
        execution: ExecutionResult,
    ) -> None:
        raise ReproductionError("artifact write failed")

    monkeypatch.setattr(ReproductionArtifacts, "write_build_log", fail_log_write)

    with pytest.raises(ReproductionError, match="artifact write failed"):
        reproducer(tmp_path / "state", MarkerMavenExecutor()).reproduce(
            task(repository, base_commit, updated_commit),
            run_id="artifact-failure-run",
        )

    worktrees = run_git(CommandRunner(), repository, "worktree", "list", "--porcelain")
    assert worktrees.count("worktree ") == 1


@pytest.mark.parametrize("status", [ExecutionStatus.TIMEOUT, ExecutionStatus.ERROR])
def test_execution_problem_is_distinct_from_build_failure(status: ExecutionStatus) -> None:
    result = classify_reproduction(ExecutionResult(status=status), None)

    assert result is ReproductionStatus.EXECUTION_ERROR


def test_reproducer_rejects_missing_commit(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base_commit, _ = create_marker_repository(repository)

    with pytest.raises(ReproductionError, match="updated commit does not exist"):
        reproducer(tmp_path / "state", MarkerMavenExecutor()).reproduce(
            task(repository, base_commit, "missing"),
            run_id="invalid-run",
        )

    assert not (tmp_path / "state").exists()


def test_reproducer_rejects_non_git_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()

    with pytest.raises(ReproductionError, match="not a Git repository"):
        reproducer(tmp_path / "state", MarkerMavenExecutor()).reproduce(
            task(repository, "base", "updated"),
            run_id="invalid-repository-run",
        )


def test_reproduction_leaves_complete_repository_state_unchanged(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base_commit, updated_commit = create_marker_repository(repository)
    (repository / "tracked.txt").write_text("user modification\n", encoding="utf-8")
    (repository / "revision.txt").write_text("staged user change\n", encoding="utf-8")
    (repository / "user-notes.txt").write_text("existing untracked file\n", encoding="utf-8")
    runner = CommandRunner()
    run_git(runner, repository, "add", "revision.txt")
    status_before = run_git(runner, repository, "status", "--porcelain=v1")
    head_before = run_git(runner, repository, "rev-parse", "HEAD")
    index_before = run_git(runner, repository, "diff", "--cached", "--binary")
    state_root = tmp_path / "external-state"

    result = reproducer(state_root, MarkerMavenExecutor()).reproduce(
        task(repository, base_commit, updated_commit),
        run_id="isolation-run",
    )

    assert run_git(runner, repository, "status", "--porcelain=v1") == status_before
    assert run_git(runner, repository, "rev-parse", "HEAD") == head_before
    assert run_git(runner, repository, "diff", "--cached", "--binary") == index_before
    assert (repository / "tracked.txt").read_text() == "user modification\n"
    assert (repository / "revision.txt").read_text() == "staged user change\n"
    assert (repository / "user-notes.txt").read_text() == "existing untracked file\n"
    assert not (repository / ".bumpshield").exists()
    assert result.artifact_directory == state_root / "runs" / "isolation-run"
    assert (result.artifact_directory / "reproduction.json").is_file()


def test_state_root_inside_repository_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base_commit, updated_commit = create_marker_repository(repository)

    with pytest.raises(ReproductionError, match="outside analyzed repository"):
        reproducer(repository / "runtime-state", MarkerMavenExecutor()).reproduce(
            task(repository, base_commit, updated_commit),
            run_id="unsafe-state-run",
        )

    assert not (repository / "runtime-state").exists()


def test_run_ids_are_unique_and_directory_safe() -> None:
    first = generate_run_id()
    second = generate_run_id()

    assert first != second
    assert len(first) == 32
    assert first.isalnum()
