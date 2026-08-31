"""Bounded, structured external command execution."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from bumpshield.config import DEFAULT_COMMAND_TIMEOUT_SECONDS
from bumpshield.models import CommandResult

LOGGER = logging.getLogger(__name__)


class CommandExecutionError(RuntimeError):
    """Raised when command infrastructure prevents process execution."""

    def __init__(self, command: tuple[str, ...], cwd: Path, reason: OSError) -> None:
        self.command = command
        self.cwd = cwd
        self.reason = reason
        super().__init__(f"could not execute {command[0]!r} in {cwd}: {reason}")


class CommandRunner:
    """Run argument-list commands without a shell and capture their results."""

    def __init__(self, default_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> None:
        if default_timeout <= 0:
            raise ValueError("default_timeout must be positive")
        self.default_timeout = default_timeout

    def run(
        self,
        command: Sequence[str | os.PathLike[str]],
        *,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Run one command and return output, status, timing, and timeout data.

        Non-zero process exits are normal results. Operating-system failures such
        as a missing executable or invalid working directory raise
        ``CommandExecutionError``.
        """
        if isinstance(command, (str, bytes)):
            raise TypeError("command must be an argument sequence, not a shell string")
        normalized_command = tuple(os.fspath(argument) for argument in command)
        if not normalized_command:
            raise ValueError("command must not be empty")

        effective_timeout = self.default_timeout if timeout is None else timeout
        if effective_timeout <= 0:
            raise ValueError("timeout must be positive")
        working_directory = Path.cwd() if cwd is None else Path(cwd)
        working_directory = working_directory.resolve()

        LOGGER.debug("Running command %r in %s", normalized_command, working_directory)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                normalized_command,
                cwd=working_directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=effective_timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            duration = time.monotonic() - started
            stdout = _timeout_text(error.stdout)
            stderr = _timeout_text(error.stderr)
            LOGGER.warning(
                "Command %r timed out after %.3f seconds",
                normalized_command,
                duration,
            )
            return CommandResult(
                command=normalized_command,
                cwd=working_directory,
                exit_code=None,
                stdout=stdout,
                stderr=stderr,
                duration_seconds=duration,
                timed_out=True,
            )
        except OSError as error:
            raise CommandExecutionError(normalized_command, working_directory, error) from error

        duration = time.monotonic() - started
        LOGGER.debug(
            "Command %r exited %d after %.3f seconds",
            normalized_command,
            completed.returncode,
            duration,
        )
        return CommandResult(
            command=normalized_command,
            cwd=working_directory,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
            timed_out=False,
        )


def _timeout_text(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output

