from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from bumpshield.execution.command_runner import CommandExecutionError
from bumpshield.execution.javap import JavapExecutor
from bumpshield.models import CommandResult, ExecutionStatus


class RecordingRunner:
    def __init__(
        self,
        *,
        exit_code: int | None = 0,
        timed_out: bool = False,
        error: CommandExecutionError | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.error = error
        self.calls: list[tuple[tuple[str, ...], Path, float | None]] = []

    def run(
        self,
        command: Sequence[str | os.PathLike[str]],
        *,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        normalized = tuple(os.fspath(item) for item in command)
        directory = Path(cwd or Path.cwd()).resolve()
        self.calls.append((normalized, directory, timeout))
        if self.error:
            raise self.error
        return CommandResult(
            command=normalized,
            cwd=directory,
            exit_code=self.exit_code,
            stdout="public class org.example.Parser {}\n",
            stderr="failure\n" if self.exit_code else "",
            duration_seconds=0.2,
            timed_out=self.timed_out,
        )


def test_javap_uses_public_api_argument_list_classpath_and_timeout(tmp_path: Path) -> None:
    artifact = tmp_path / "parser.jar"
    artifact.write_bytes(b"fixture")
    runner = RecordingRunner()

    result = JavapExecutor(runner=runner, timeout=17).inspect(
        artifact, "org.example.Parser"
    )

    assert result.execution.status is ExecutionStatus.PASS
    assert runner.calls == [
        (
            (
                "javap",
                "-public",
                "-classpath",
                str(artifact.resolve()),
                "org.example.Parser",
            ),
            tmp_path.resolve(),
            17,
        )
    ]


def test_javap_failure_timeout_and_missing_tool_are_distinct(tmp_path: Path) -> None:
    artifact = tmp_path / "parser.jar"
    artifact.write_bytes(b"fixture")
    failed = JavapExecutor(runner=RecordingRunner(exit_code=1)).inspect(
        artifact, "org.example.Parser"
    )
    timed_out = JavapExecutor(
        runner=RecordingRunner(exit_code=None, timed_out=True)
    ).inspect(artifact, "org.example.Parser")
    missing_error = CommandExecutionError(
        ("javap",), tmp_path, FileNotFoundError("javap missing")
    )
    missing = JavapExecutor(runner=RecordingRunner(error=missing_error)).inspect(
        artifact, "org.example.Parser"
    )

    assert failed.execution.status is ExecutionStatus.FAIL
    assert timed_out.execution.status is ExecutionStatus.TIMEOUT
    assert missing.execution.status is ExecutionStatus.ERROR
    assert "javap missing" in (missing.execution.detail or "")

