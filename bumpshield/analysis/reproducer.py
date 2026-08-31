"""Deterministic base-versus-updated regression reproduction."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.execution.maven import MavenExecution, MavenExecutor
from bumpshield.models import (
    ExecutionResult,
    ExecutionStatus,
    ReproductionResult,
    ReproductionStatus,
    RevisionExecution,
    TaskSpec,
    WorkspaceKind,
)
from bumpshield.run import (
    RunSetupError,
    execution_log_text,
    generate_run_id,
    require_external_path,
    validate_task_repository,
)
from bumpshield.repo.workspace import WorkspaceError, WorkspaceManager
from bumpshield.task_io import task_spec_to_dict

LOGGER = logging.getLogger(__name__)


class ReproductionError(RuntimeError):
    """Raised when reproduction setup or artifact persistence cannot continue."""


class RegressionReproducer:
    """Validate, execute, classify, persist, and clean one reproduction run."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        maven: MavenExecution | None = None,
        config: BumpShieldConfig | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.maven = maven if maven is not None else MavenExecutor(runner=self.runner)
        self.config = config if config is not None else BumpShieldConfig()

    def reproduce(self, task: TaskSpec, run_id: str | None = None) -> ReproductionResult:
        """Reproduce one task using detached, temporary Git worktrees."""
        try:
            repository, repository_root = validate_task_repository(task, self.runner)
        except RunSetupError as error:
            raise ReproductionError(str(error)) from error
        effective_run_id = run_id or generate_run_id()
        artifact_path = self.config.run_directory(effective_run_id).resolve()
        try:
            require_external_path(artifact_path, repository_root)
        except RunSetupError as error:
            raise ReproductionError(str(error)) from error
        artifacts = ReproductionArtifacts.create(artifact_path)
        artifacts.write_task(task)

        try:
            with WorkspaceManager(repository, effective_run_id) as workspaces:
                base_workspace = workspaces.create(task.base_commit, WorkspaceKind.BASE)
                base_execution = self.maven.execute(base_workspace)
                base = RevisionExecution(task.base_commit, base_execution)
                artifacts.write_build_log("base", base_execution)

                updated: RevisionExecution | None = None
                if base_execution.status is ExecutionStatus.PASS:
                    updated_workspace = workspaces.create(
                        task.updated_commit,
                        WorkspaceKind.UPDATED,
                    )
                    updated_execution = self.maven.execute(updated_workspace)
                    updated = RevisionExecution(task.updated_commit, updated_execution)
                    artifacts.write_build_log("updated", updated_execution)
        except WorkspaceError as error:
            raise ReproductionError(str(error)) from error

        result = ReproductionResult(
            run_id=effective_run_id,
            status=classify_reproduction(base.execution, updated.execution if updated else None),
            task=task,
            artifact_directory=artifacts.path,
            base=base,
            updated=updated,
        )
        artifacts.write_result(result)
        return result


def classify_reproduction(
    base: ExecutionResult,
    updated: ExecutionResult | None,
) -> ReproductionStatus:
    """Classify execution statuses without interpreting build output."""
    if base.status in {ExecutionStatus.TIMEOUT, ExecutionStatus.ERROR}:
        return ReproductionStatus.EXECUTION_ERROR
    if base.status is ExecutionStatus.FAIL:
        return ReproductionStatus.BASE_FAILED
    if updated is None or updated.status in {
        ExecutionStatus.TIMEOUT,
        ExecutionStatus.ERROR,
    }:
        return ReproductionStatus.EXECUTION_ERROR
    if updated.status is ExecutionStatus.PASS:
        return ReproductionStatus.UPDATED_PASSED
    return ReproductionStatus.CONFIRMED


class ReproductionArtifacts:
    """Single owner for Phase 1 run artifact formats."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def create(cls, path: Path) -> ReproductionArtifacts:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise ReproductionError(f"could not create run directory {path}: {error}") from error
        return cls(path)

    def write_task(self, task: TaskSpec) -> None:
        self._write_json("task.json", task_spec_to_dict(task))

    def write_build_log(self, revision: str, execution: ExecutionResult) -> None:
        self._write_text(f"{revision}-build.log", execution_log_text(execution))

    def write_result(self, result: ReproductionResult) -> None:
        self._write_json("reproduction.json", reproduction_result_to_dict(result))

    def _write_json(self, filename: str, data: dict[str, object]) -> None:
        self._write_text(filename, json.dumps(data, indent=2) + "\n")

    def _write_text(self, filename: str, text: str) -> None:
        path = self.path / filename
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as error:
            raise ReproductionError(f"could not write artifact {path}: {error}") from error


def reproduction_result_to_dict(result: ReproductionResult) -> dict[str, object]:
    """Return canonical JSON-compatible reproduction result data."""
    return {
        "run_id": result.run_id,
        "status": result.status.value,
        "base": _revision_to_dict(result.base),
        "updated": _revision_to_dict(result.updated) if result.updated else None,
    }


def _revision_to_dict(revision: RevisionExecution) -> dict[str, object]:
    command = revision.execution.commands[-1] if revision.execution.commands else None
    return {
        "commit": revision.commit,
        "status": revision.execution.status.value,
        "exit_code": command.exit_code if command else None,
        "duration_seconds": command.duration_seconds if command else None,
        "timed_out": command.timed_out if command else False,
        "command": list(command.command) if command else None,
        "workspace": str(command.cwd) if command else None,
        "detail": revision.execution.detail,
    }
