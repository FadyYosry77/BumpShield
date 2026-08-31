from __future__ import annotations

from pathlib import Path

import pytest

from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import WorkspaceKind
from bumpshield.repo.git import GitRepository, GitRepositoryError
from bumpshield.repo.workspace import WorkspaceManager


def run_git(runner: CommandRunner, cwd: Path, *arguments: str) -> None:
    result = runner.run(["git", *arguments], cwd=cwd, timeout=5)
    assert result.exit_code == 0, result.stderr


def create_repository(path: Path) -> tuple[GitRepository, str]:
    runner = CommandRunner(default_timeout=5)
    path.mkdir()
    run_git(runner, path, "init", "--quiet")
    run_git(runner, path, "config", "user.name", "BumpShield Tests")
    run_git(runner, path, "config", "user.email", "tests@example.invalid")
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    run_git(runner, path, "add", "README.md")
    run_git(runner, path, "commit", "--quiet", "-m", "fixture")
    repository = GitRepository(path, runner=runner)
    return repository, repository.get_current_commit()


def test_git_repository_operations(tmp_path: Path) -> None:
    path = tmp_path / "repository"
    repository, commit = create_repository(path)

    assert repository.is_git_repository() is True
    repository.verify()
    assert repository.get_repository_root() == path.resolve()
    assert repository.get_current_commit() == commit
    assert repository.commit_exists(commit) is True
    assert repository.commit_exists("not-a-commit") is False
    assert repository.get_working_tree_status() == ""


def test_git_status_reports_changes(tmp_path: Path) -> None:
    path = tmp_path / "repository"
    repository, _ = create_repository(path)
    (path / "README.md").write_text("changed\n", encoding="utf-8")

    assert repository.get_working_tree_status().startswith(" M README.md")


def test_non_repository_is_detected(tmp_path: Path) -> None:
    repository = GitRepository(tmp_path)

    assert repository.is_git_repository() is False
    with pytest.raises(GitRepositoryError, match="not a Git repository"):
        repository.verify()


def test_workspace_manager_creates_and_cleans_detached_worktrees(tmp_path: Path) -> None:
    path = tmp_path / "repository"
    repository, base_commit = create_repository(path)
    (path / "README.md").write_text("updated\n", encoding="utf-8")
    run_git(repository.runner, path, "add", "README.md")
    run_git(repository.runner, path, "commit", "--quiet", "-m", "updated")
    updated_commit = repository.get_current_commit()
    (path / "README.md").write_text("uncommitted\n", encoding="utf-8")
    original_status = repository.get_working_tree_status()
    original_head = repository.get_current_commit()

    with WorkspaceManager(repository, "workspace-test") as manager:
        root = manager.root
        base = manager.create(base_commit, WorkspaceKind.BASE)
        updated = manager.create(updated_commit, WorkspaceKind.UPDATED)
        repair = manager.create(updated_commit, WorkspaceKind.REPAIR)

        assert (base.path / "README.md").read_text(encoding="utf-8") == "fixture\n"
        assert (updated.path / "README.md").read_text(encoding="utf-8") == "updated\n"
        assert (repair.path / "README.md").read_text(encoding="utf-8") == "updated\n"
        assert repository.get_current_commit() == original_head
        assert repository.get_working_tree_status() == original_status
        assert (path / "README.md").read_text(encoding="utf-8") == "uncommitted\n"

    assert not root.exists()
    assert repository.get_current_commit() == original_head
    assert repository.get_working_tree_status() == original_status
    worktrees = repository.runner.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=path,
        timeout=5,
    )
    assert worktrees.stdout.count("worktree ") == 1
