"""Centralized basic Git repository operations."""

from __future__ import annotations

from pathlib import Path

from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import CommandResult


class GitRepositoryError(RuntimeError):
    """Raised when a required Git operation does not succeed."""


class GitRepository:
    """Centralized operations for one local Git repository."""

    def __init__(self, path: Path, runner: CommandRunner | None = None) -> None:
        self.path = Path(path).resolve()
        self.runner = runner or CommandRunner()

    def is_git_repository(self) -> bool:
        """Return whether the path belongs to a Git working tree."""
        if not self.path.is_dir():
            return False
        result = self._run("rev-parse", "--is-inside-work-tree")
        return result.exit_code == 0 and result.stdout.strip() == "true"

    def verify(self) -> None:
        """Raise a meaningful error unless the path is a Git repository."""
        if not self.is_git_repository():
            raise GitRepositoryError(f"not a Git repository: {self.path}")

    def get_current_commit(self) -> str:
        """Return the commit currently checked out."""
        return self._require_success(self._run("rev-parse", "HEAD"), "read HEAD").stdout.strip()

    def commit_exists(self, commit: str) -> bool:
        """Return whether a reference resolves to a commit object."""
        if not commit or commit.startswith("-"):
            return False
        result = self._run("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
        return result.exit_code == 0

    def get_repository_root(self) -> Path:
        """Return Git's canonical root for this working tree."""
        result = self._require_success(
            self._run("rev-parse", "--show-toplevel"),
            "read repository root",
        )
        return Path(result.stdout.strip()).resolve()

    def get_working_tree_status(self) -> str:
        """Return machine-readable porcelain working-tree status."""
        result = self._require_success(
            self._run("status", "--porcelain"),
            "read working-tree status",
        )
        return result.stdout

    def list_tracked_files(self) -> tuple[Path, ...]:
        """Return repository-relative tracked files without shell parsing."""
        result = self._require_success(
            self._run("ls-files", "-z"),
            "list tracked files",
        )
        return tuple(Path(value) for value in result.stdout.split("\0") if value)

    def status_porcelain(self) -> str:
        """Return NUL-delimited status including every untracked file."""
        return self._require_success(
            self._run(
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ),
            "inspect repair changes",
        ).stdout

    def mark_intent_to_add(self, paths: tuple[Path, ...]) -> None:
        """Make selected untracked files visible to Git diff without staging content."""
        if not paths:
            return
        arguments = tuple(str(path) for path in paths)
        self._require_success(
            self._run("add", "--intent-to-add", "--", *arguments),
            "include new files in repair diff",
        )

    def diff_head(self) -> str:
        """Return exact binary-capable repair diff against HEAD."""
        return self._require_success(
            self._run(
                "diff",
                "--binary",
                "--no-ext-diff",
                "--full-index",
                "HEAD",
                "--",
            ),
            "capture repair patch",
        ).stdout

    def diff_numstat(self) -> str:
        """Return deterministic per-file line statistics against HEAD."""
        return self._require_success(
            self._run("diff", "--numstat", "-z", "HEAD", "--"),
            "capture repair patch statistics",
        ).stdout

    def diff_name_status(self) -> str:
        """Return NUL-delimited changed-file classifications against HEAD."""
        return self._require_success(
            self._run("diff", "--name-status", "-z", "HEAD", "--"),
            "classify repair patch files",
        ).stdout

    def add_detached_worktree(self, path: Path, commit: str) -> None:
        """Create a detached worktree without changing the source checkout."""
        destination = Path(path).resolve()
        self._require_success(
            self._run("worktree", "add", "--detach", str(destination), commit),
            f"create detached worktree at {destination}",
        )

    def remove_worktree(self, path: Path) -> None:
        """Remove one known worktree and its Git registration."""
        destination = Path(path).resolve()
        self._require_success(
            self._run("worktree", "remove", "--force", str(destination)),
            f"remove worktree at {destination}",
        )

    def prune_worktrees(self) -> None:
        """Remove stale worktree administrative records."""
        self._require_success(
            self._run("worktree", "prune"),
            "prune stale worktrees",
        )

    def _run(self, *arguments: str) -> CommandResult:
        return self.runner.run(("git", *arguments), cwd=self.path)

    def _require_success(self, result: CommandResult, operation: str) -> CommandResult:
        if result.timed_out:
            raise GitRepositoryError(f"Git timed out while trying to {operation}")
        if result.exit_code != 0:
            detail = result.stderr.strip() or f"exit code {result.exit_code}"
            raise GitRepositoryError(f"could not {operation}: {detail}")
        return result
