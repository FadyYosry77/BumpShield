"""Shared setup primitives for deterministic BumpShield runs."""

from __future__ import annotations

import shlex
import uuid
from pathlib import Path

from bumpshield.execution.command_runner import CommandExecutionError, CommandRunner
from bumpshield.models import ExecutionResult, TaskSpec
from bumpshield.repo.git import GitRepository, GitRepositoryError


class RunSetupError(RuntimeError):
    """Raised when shared repository or run-path setup is invalid."""


def validate_task_repository(
    task: TaskSpec,
    runner: CommandRunner,
) -> tuple[GitRepository, Path]:
    """Validate the repository and both requested commits once, centrally."""
    repository = GitRepository(task.repository, runner=runner)
    try:
        repository.verify()
        if not repository.commit_exists(task.base_commit):
            raise RunSetupError(f"base commit does not exist: {task.base_commit}")
        if not repository.commit_exists(task.updated_commit):
            raise RunSetupError(f"updated commit does not exist: {task.updated_commit}")
        return repository, repository.get_repository_root()
    except (GitRepositoryError, CommandExecutionError) as error:
        raise RunSetupError(str(error)) from error


def generate_run_id() -> str:
    """Generate a unique filesystem-safe run identifier."""
    return uuid.uuid4().hex


def require_external_path(path: Path, repository: Path) -> None:
    """Reject persistent state located inside the analyzed repository."""
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(repository.resolve())
    except ValueError:
        return
    raise RunSetupError(
        f"state directory must be outside analyzed repository: {resolved_path}"
    )


def execution_log_text(execution: ExecutionResult) -> str:
    """Format commands with separate stdout and stderr evidence sections."""
    sections: list[str] = []
    for command in execution.commands:
        sections.extend(
            (
                f"Command: {shlex.join(command.command)}\n",
                f"Working directory: {command.cwd}\n",
                f"Exit code: {command.exit_code}\n",
                f"Timed out: {str(command.timed_out).lower()}\n",
                "\n[stdout]\n",
                command.stdout,
                "\n[stderr]\n",
                command.stderr,
            )
        )
    if execution.detail:
        sections.extend(("\n[execution error]\n", execution.detail, "\n"))
    return "".join(sections)
