from __future__ import annotations

import json
from pathlib import Path

import pytest

from bumpshield.analysis.dependency_diff import (
    DependencyAnalysisError,
    DependencyAnalyzer,
)
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import (
    CommandResult,
    DependencyChangeKind,
    DependencyTreeCommandResult,
    DependencyUpgrade,
    ExecutionResult,
    ExecutionStatus,
    TaskSpec,
)
from bumpshield.repo.workspace import RepositoryWorkspace


BASE_TREE = """\
org.example:app:jar:1.0
+- org.example:foo:jar:1.0:compile
|  \\- org.example:helper:jar:1.0:runtime
\\- org.example:stable:jar:4.0:test
"""

UPDATED_TREE = """\
org.example:app:jar:1.1
+- org.example:foo:jar:2.0:compile
|  +- org.example:helper:jar:2.0:runtime
|  \\- org.example:new-helper:jar:1.0:runtime
\\- org.example:stable:jar:4.0:test
"""


def run_git(runner: CommandRunner, cwd: Path, *arguments: str) -> str:
    result = runner.run(["git", *arguments], cwd=cwd, timeout=5)
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def create_dependency_repository(path: Path) -> tuple[str, str]:
    runner = CommandRunner(default_timeout=5)
    path.mkdir()
    run_git(runner, path, "init", "--quiet")
    run_git(runner, path, "config", "user.name", "BumpShield Tests")
    run_git(runner, path, "config", "user.email", "tests@example.invalid")
    (path / "dependency-tree.txt").write_text(BASE_TREE, encoding="utf-8")
    (path / "tracked.txt").write_text("committed\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "base")
    base_commit = run_git(runner, path, "rev-parse", "HEAD")
    (path / "dependency-tree.txt").write_text(UPDATED_TREE, encoding="utf-8")
    (path / "revision.txt").write_text("updated\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "updated")
    updated_commit = run_git(runner, path, "rev-parse", "HEAD")
    return base_commit, updated_commit


def make_task(repository: Path, base: str, updated: str) -> TaskSpec:
    return TaskSpec(
        repository=repository,
        base_commit=base,
        updated_commit=updated,
        target_dependency=DependencyUpgrade(
            group_id="org.example",
            artifact_id="foo",
            old_version="1.0",
            new_version="2.0",
        ),
    )


class FixtureDependencyMaven:
    def __init__(self, failure: ExecutionStatus | None = None) -> None:
        self.failure = failure
        self.calls: list[Path] = []

    def dependency_tree(
        self,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> DependencyTreeCommandResult:
        self.calls.append(workspace.path)
        if self.failure is None:
            raw_output = (workspace.path / "dependency-tree.txt").read_text(
                encoding="utf-8"
            )
            output_file.write_text(raw_output, encoding="utf-8")
            status = ExecutionStatus.PASS
            exit_code: int | None = 0
            timed_out = False
        else:
            raw_output = ""
            status = self.failure
            exit_code = None if status is ExecutionStatus.TIMEOUT else 1
            timed_out = status is ExecutionStatus.TIMEOUT
        command = CommandResult(
            command=("mvn", "-B", "dependency:tree", f"-DoutputFile={output_file}"),
            cwd=workspace.path,
            exit_code=exit_code,
            stdout="maven console\n",
            stderr="maven failure\n" if status is not ExecutionStatus.PASS else "",
            duration_seconds=0.2,
            timed_out=timed_out,
        )
        return DependencyTreeCommandResult(
            execution=ExecutionResult(status=status, commands=(command,)),
            output_file=output_file,
            raw_output=raw_output,
        )


def test_dependency_analysis_persists_all_external_artifacts(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base, updated = create_dependency_repository(repository)
    state_root = tmp_path / "state"
    maven = FixtureDependencyMaven()

    result = DependencyAnalyzer(
        maven=maven,
        config=BumpShieldConfig(state_root=state_root),
    ).analyze(make_task(repository, base, updated), run_id="dependencies-run")

    expected_path = state_root / "runs" / "dependencies-run"
    assert result.artifact_directory == expected_path
    assert result.diff.target is not None and result.diff.target.matched
    assert len(result.diff.of_kind(DependencyChangeKind.UPDATED)) == 2
    assert len(result.diff.of_kind(DependencyChangeKind.ADDED)) == 1
    assert len(result.diff.of_kind(DependencyChangeKind.UNCHANGED)) == 1
    assert all(not workspace.exists() for workspace in maven.calls)
    assert {path.name for path in expected_path.iterdir()} == {
        "task.json",
        "base-dependency-tree.txt",
        "updated-dependency-tree.txt",
        "dependencies-before.json",
        "dependencies-after.json",
        "dependency-diff.json",
    }
    parsed_before = json.loads((expected_path / "dependencies-before.json").read_text())
    helper = next(
        node for node in parsed_before["dependencies"] if node["artifact_id"] == "helper"
    )
    assert helper["depth"] == 2
    assert helper["parent"]["artifact_id"] == "foo"
    persisted_diff = json.loads((expected_path / "dependency-diff.json").read_text())
    assert persisted_diff["target"]["matched"] is True
    assert persisted_diff["counts"]["updated"] == 2
    assert not (repository / ".bumpshield").exists()


def test_dependency_analysis_leaves_complete_source_state_unchanged(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    base, updated = create_dependency_repository(repository)
    (repository / "tracked.txt").write_text("unstaged user edit\n", encoding="utf-8")
    (repository / "revision.txt").write_text("staged user edit\n", encoding="utf-8")
    (repository / "user-notes.txt").write_text("existing untracked\n", encoding="utf-8")
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "add", "revision.txt")
    status_before = run_git(runner, repository, "status", "--porcelain=v1")
    head_before = run_git(runner, repository, "rev-parse", "HEAD")
    index_before = run_git(runner, repository, "diff", "--cached", "--binary")

    DependencyAnalyzer(
        maven=FixtureDependencyMaven(),
        config=BumpShieldConfig(state_root=tmp_path / "external-state"),
    ).analyze(make_task(repository, base, updated), run_id="isolation-run")

    assert run_git(runner, repository, "status", "--porcelain=v1") == status_before
    assert run_git(runner, repository, "rev-parse", "HEAD") == head_before
    assert run_git(runner, repository, "diff", "--cached", "--binary") == index_before
    assert (repository / "tracked.txt").read_text() == "unstaged user edit\n"
    assert (repository / "revision.txt").read_text() == "staged user edit\n"
    assert (repository / "user-notes.txt").read_text() == "existing untracked\n"
    assert not (repository / ".bumpshield").exists()


def test_dependency_collection_failure_cleans_worktrees_and_stays_distinct(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    base, updated = create_dependency_repository(repository)
    runner = CommandRunner(default_timeout=5)

    with pytest.raises(DependencyAnalysisError, match="TIMEOUT"):
        DependencyAnalyzer(
            maven=FixtureDependencyMaven(ExecutionStatus.TIMEOUT),
            config=BumpShieldConfig(state_root=tmp_path / "state"),
        ).analyze(make_task(repository, base, updated), run_id="timeout-run")

    worktrees = run_git(runner, repository, "worktree", "list", "--porcelain")
    assert worktrees.count("worktree ") == 1
    raw_log = tmp_path / "state" / "runs" / "timeout-run" / "base-dependency-tree.txt"
    assert "maven console" in raw_log.read_text()


def test_dependency_analysis_rejects_state_inside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    base, updated = create_dependency_repository(repository)

    with pytest.raises(DependencyAnalysisError, match="outside analyzed repository"):
        DependencyAnalyzer(
            maven=FixtureDependencyMaven(),
            config=BumpShieldConfig(state_root=repository / "state"),
        ).analyze(make_task(repository, base, updated), run_id="unsafe-run")

    assert not (repository / "state").exists()
