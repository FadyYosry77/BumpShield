from __future__ import annotations

import sys
from pathlib import Path

import pytest

from bumpshield.execution.command_runner import CommandExecutionError, CommandRunner


def test_successful_command_captures_stdout() -> None:
    result = CommandRunner().run(
        [sys.executable, "-c", "print('ready')"],
        timeout=5,
    )

    assert result.exit_code == 0
    assert result.stdout == "ready\n"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.duration_seconds >= 0


def test_non_zero_command_is_structured_and_captures_stderr() -> None:
    result = CommandRunner().run(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('bad', file=sys.stderr); sys.exit(7)",
        ],
        timeout=5,
    )

    assert result.exit_code == 7
    assert result.stdout == "out\n"
    assert result.stderr == "bad\n"
    assert result.timed_out is False


def test_timeout_returns_structured_result() -> None:
    result = CommandRunner().run(
        [
            sys.executable,
            "-c",
            "import time; print('started', flush=True); time.sleep(2)",
        ],
        timeout=0.05,
    )

    assert result.exit_code is None
    assert result.timed_out is True
    assert "started" in result.stdout
    assert result.duration_seconds >= 0.05


def test_working_directory_is_used(tmp_path: Path) -> None:
    result = CommandRunner().run(
        [sys.executable, "-c", "from pathlib import Path; print(Path.cwd())"],
        cwd=tmp_path,
        timeout=5,
    )

    assert result.exit_code == 0
    assert result.cwd == tmp_path.resolve()
    assert Path(result.stdout.strip()) == tmp_path.resolve()


def test_shell_string_is_rejected() -> None:
    with pytest.raises(TypeError, match="argument sequence"):
        CommandRunner().run("echo unsafe")  # type: ignore[arg-type]


def test_missing_executable_is_infrastructure_error() -> None:
    with pytest.raises(CommandExecutionError):
        CommandRunner().run(["bumpshield-command-that-does-not-exist"], timeout=5)

