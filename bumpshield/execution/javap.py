"""Bounded public Java API metadata inspection through ``javap``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from bumpshield.config import DEFAULT_COMMAND_TIMEOUT_SECONDS
from bumpshield.execution.command_runner import CommandExecutionError, CommandRunner
from bumpshield.models import (
    ExecutionResult,
    ExecutionStatus,
    JavaApiCommandResult,
)

LOGGER = logging.getLogger(__name__)


class JavapExecution(Protocol):
    """Typed seam for deterministic Java API inspection."""

    def inspect(self, artifact: Path, class_name: str) -> JavaApiCommandResult:
        """Inspect one class from one artifact."""
        ...


class JavapExecutor:
    """Inspect public declarations without loading or executing dependency code."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        executable: str = "javap",
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.runner = runner or CommandRunner()
        self.timeout = timeout
        self.executable = executable

    def inspect(self, artifact: Path, class_name: str) -> JavaApiCommandResult:
        """Run ``javap -public`` for one class in one artifact."""
        path = Path(artifact).resolve()
        command = (self.executable, "-public", "-classpath", str(path), class_name)
        LOGGER.debug("Inspecting public API for %s in %s", class_name, path)
        try:
            result = self.runner.run(command, cwd=path.parent, timeout=self.timeout)
        except CommandExecutionError as error:
            return JavaApiCommandResult(
                execution=ExecutionResult(
                    status=ExecutionStatus.ERROR,
                    detail=str(error),
                ),
                artifact=path,
                class_name=class_name,
                raw_output="",
            )
        status = (
            ExecutionStatus.TIMEOUT
            if result.timed_out
            else ExecutionStatus.PASS
            if result.exit_code == 0
            else ExecutionStatus.FAIL
        )
        return JavaApiCommandResult(
            execution=ExecutionResult(status=status, commands=(result,)),
            artifact=path,
            class_name=class_name,
            raw_output=result.stdout,
        )
