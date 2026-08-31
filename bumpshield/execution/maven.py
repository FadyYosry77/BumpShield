"""Deterministic Maven test execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from bumpshield.config import MAVEN_TIMEOUT_SECONDS
from bumpshield.execution.command_runner import CommandExecutionError, CommandRunner
from bumpshield.models import (
    CommandResult,
    DependencyTreeCommandResult,
    ExecutionResult,
    ExecutionStatus,
    ResolvedArtifactsCommandResult,
)
from bumpshield.repo.workspace import RepositoryWorkspace

LOGGER = logging.getLogger(__name__)


class MavenExecution(Protocol):
    """Typed seam for deterministic Maven execution."""

    def execute(self, workspace: RepositoryWorkspace) -> ExecutionResult:
        """Execute one workspace and return structured status."""
        ...


class MavenDependencyExecution(Protocol):
    """Typed seam for Maven resolved-dependency collection."""

    def dependency_tree(
        self,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> DependencyTreeCommandResult:
        """Collect one workspace's raw resolved dependency tree."""
        ...


class MavenEvidenceExecution(MavenDependencyExecution, MavenExecution, Protocol):
    """Commands required by standalone deterministic API evidence collection."""

    def artifact_list(
        self,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> ResolvedArtifactsCommandResult:
        """Collect resolved dependency coordinates and absolute artifact paths."""
        ...


class MavenExecutor:
    """Run Maven's test lifecycle through ``CommandRunner``."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        timeout: float = MAVEN_TIMEOUT_SECONDS,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.runner = runner or CommandRunner()
        self.timeout = timeout

    def execute(self, workspace: RepositoryWorkspace) -> ExecutionResult:
        """Run Maven tests and classify process outcome without parsing logs."""
        return self.execute_lifecycle(workspace, "test")

    def execute_lifecycle(
        self,
        workspace: RepositoryWorkspace,
        goal: str,
    ) -> ExecutionResult:
        """Run one validated compile or test lifecycle goal independently."""
        command = self.lifecycle_command_for(workspace.path, goal)
        LOGGER.debug("Running Maven for %s with %r", workspace.commit, command)
        try:
            result = self.runner.run(command, cwd=workspace.path, timeout=self.timeout)
        except CommandExecutionError as error:
            LOGGER.error("Maven infrastructure error: %s", error)
            return ExecutionResult(status=ExecutionStatus.ERROR, detail=str(error))

        return ExecutionResult(status=self._classify(result), commands=(result,))

    def dependency_tree(
        self,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> DependencyTreeCommandResult:
        """Collect Maven's text dependency tree into an external output file."""
        destination = Path(output_file).resolve()
        command = self.dependency_tree_command_for(workspace.path, destination)
        LOGGER.debug(
            "Collecting Maven dependency tree for %s with %r",
            workspace.commit,
            command,
        )
        try:
            command_result = self.runner.run(
                command,
                cwd=workspace.path,
                timeout=self.timeout,
            )
        except CommandExecutionError as error:
            LOGGER.error("Maven infrastructure error: %s", error)
            return DependencyTreeCommandResult(
                execution=ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    detail=str(error),
                ),
                output_file=destination,
                raw_output="",
            )

        execution = ExecutionResult(
            status=self._classify(command_result),
            commands=(command_result,),
        )
        raw_output = ""
        if destination.is_file():
            try:
                raw_output = destination.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                execution = ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    commands=(command_result,),
                    detail=f"could not read dependency tree {destination}: {error}",
                )
        elif execution.status is ExecutionStatus.PASS:
            execution = ExecutionResult(
                status=ExecutionStatus.ERROR,
                commands=(command_result,),
                detail=f"Maven produced no dependency tree at {destination}",
            )

        return DependencyTreeCommandResult(
            execution=execution,
            output_file=destination,
            raw_output=raw_output,
        )

    def artifact_list(
        self,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> ResolvedArtifactsCommandResult:
        """Collect dependency paths without assuming Maven's local repository."""
        destination = Path(output_file).resolve()
        command = self.artifact_list_command_for(workspace.path, destination)
        LOGGER.debug("Collecting Maven artifact paths for %s", workspace.commit)
        try:
            command_result = self.runner.run(
                command,
                cwd=workspace.path,
                timeout=self.timeout,
            )
        except CommandExecutionError as error:
            LOGGER.error("Maven infrastructure error: %s", error)
            return ResolvedArtifactsCommandResult(
                execution=ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    detail=str(error),
                ),
                output_file=destination,
                raw_output="",
            )

        execution = ExecutionResult(
            status=self._classify(command_result),
            commands=(command_result,),
        )
        raw_output = ""
        if destination.is_file():
            try:
                raw_output = destination.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                execution = ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    commands=(command_result,),
                    detail=f"could not read artifact list {destination}: {error}",
                )
        elif execution.status is ExecutionStatus.PASS:
            execution = ExecutionResult(
                status=ExecutionStatus.ERROR,
                commands=(command_result,),
                detail=f"Maven produced no artifact list at {destination}",
            )
        return ResolvedArtifactsCommandResult(
            execution=execution,
            output_file=destination,
            raw_output=raw_output,
        )

    @staticmethod
    def command_for(project: Path) -> tuple[str, ...]:
        """Prefer Maven wrapper; otherwise use system Maven."""
        return MavenExecutor.lifecycle_command_for(project, "test")

    @staticmethod
    def lifecycle_command_for(project: Path, goal: str) -> tuple[str, ...]:
        """Build a non-executed Maven lifecycle command for one validated goal."""
        if goal not in {"compile", "test"}:
            raise ValueError(f"unsupported Maven lifecycle goal: {goal}")
        return MavenExecutor._executable_for(project), "-B", goal

    @staticmethod
    def dependency_tree_command_for(
        project: Path,
        output_file: Path,
    ) -> tuple[str, ...]:
        """Build the broadly compatible Maven text-tree command."""
        return (
            MavenExecutor._executable_for(project),
            "-B",
            "dependency:tree",
            f"-DoutputFile={Path(output_file).resolve()}",
            "-DappendOutput=true",
        )

    @staticmethod
    def artifact_list_command_for(
        project: Path,
        output_file: Path,
    ) -> tuple[str, ...]:
        """Build observational artifact-path command using external output."""
        return (
            MavenExecutor._executable_for(project),
            "-B",
            "dependency:list",
            f"-DoutputFile={Path(output_file).resolve()}",
            "-DoutputAbsoluteArtifactFilename=true",
            "-DappendOutput=true",
        )

    @staticmethod
    def _executable_for(project: Path) -> str:
        return "./mvnw" if (Path(project) / "mvnw").is_file() else "mvn"

    @staticmethod
    def _classify(result: CommandResult) -> ExecutionStatus:
        if result.timed_out:
            return ExecutionStatus.TIMEOUT
        if result.exit_code == 0:
            return ExecutionStatus.PASS
        return ExecutionStatus.FAIL
