from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from bumpshield.execution.command_runner import CommandExecutionError
from bumpshield.execution.maven import MavenExecutor
from bumpshield.models import CommandResult, ExecutionStatus, WorkspaceKind
from bumpshield.repo.workspace import RepositoryWorkspace


class RecordingRunner:
    def __init__(
        self,
        *,
        exit_code: int | None = 0,
        timed_out: bool = False,
        error: CommandExecutionError | None = None,
        tree_output: str | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.timed_out = timed_out
        self.error = error
        self.tree_output = tree_output
        self.calls: list[tuple[tuple[str, ...], Path, float | None]] = []

    def run(
        self,
        command: Sequence[str | os.PathLike[str]],
        *,
        cwd: str | os.PathLike[str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        normalized = tuple(os.fspath(argument) for argument in command)
        working_directory = Path(cwd or Path.cwd()).resolve()
        self.calls.append((normalized, working_directory, timeout))
        if self.error:
            raise self.error
        if self.tree_output is not None:
            output_argument = next(
                argument for argument in normalized if argument.startswith("-DoutputFile=")
            )
            Path(output_argument.removeprefix("-DoutputFile=")).write_text(
                self.tree_output,
                encoding="utf-8",
            )
        return CommandResult(
            command=normalized,
            cwd=working_directory,
            exit_code=self.exit_code,
            stdout="build output\n",
            stderr="",
            duration_seconds=1.25,
            timed_out=self.timed_out,
        )


def workspace(path: Path) -> RepositoryWorkspace:
    return RepositoryWorkspace(path=path, commit="abc123", kind=WorkspaceKind.BASE)


def test_maven_wrapper_is_preferred(tmp_path: Path) -> None:
    (tmp_path / "mvnw").write_text("wrapper", encoding="utf-8")
    runner = RecordingRunner()

    result = MavenExecutor(runner=runner, timeout=12).execute(workspace(tmp_path))

    assert result.status is ExecutionStatus.PASS
    assert runner.calls == [(('./mvnw', '-B', 'test'), tmp_path.resolve(), 12)]


def test_lifecycle_command_builds_future_compile_and_test_checks(tmp_path: Path) -> None:
    assert MavenExecutor.lifecycle_command_for(tmp_path, "compile") == (
        "mvn",
        "-B",
        "compile",
    )
    (tmp_path / "mvnw").touch()
    assert MavenExecutor.lifecycle_command_for(tmp_path, "test") == (
        "./mvnw",
        "-B",
        "test",
    )
    with pytest.raises(ValueError, match="unsupported Maven lifecycle goal"):
        MavenExecutor.lifecycle_command_for(tmp_path, "verify")


def test_system_maven_is_fallback(tmp_path: Path) -> None:
    runner = RecordingRunner(exit_code=1)

    result = MavenExecutor(runner=runner).execute(workspace(tmp_path))

    assert result.status is ExecutionStatus.FAIL
    assert runner.calls[0][0] == ("mvn", "-B", "test")


def test_maven_timeout_is_not_build_failure(tmp_path: Path) -> None:
    runner = RecordingRunner(exit_code=None, timed_out=True)

    result = MavenExecutor(runner=runner).execute(workspace(tmp_path))

    assert result.status is ExecutionStatus.TIMEOUT
    assert result.commands[0].timed_out is True


def test_maven_start_failure_is_execution_error(tmp_path: Path) -> None:
    error = CommandExecutionError(
        ("mvn", "-B", "test"),
        tmp_path,
        FileNotFoundError("mvn missing"),
    )
    runner = RecordingRunner(error=error)

    result = MavenExecutor(runner=runner).execute(workspace(tmp_path))

    assert result.status is ExecutionStatus.ERROR
    assert result.commands == ()
    assert "mvn missing" in (result.detail or "")


def test_dependency_tree_prefers_wrapper_and_reads_external_output(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "mvnw").write_text("wrapper", encoding="utf-8")
    output_file = tmp_path / "state" / "tree.txt"
    output_file.parent.mkdir()
    tree = "org.example:app:jar:1.0\n"
    runner = RecordingRunner(tree_output=tree)

    result = MavenExecutor(runner=runner, timeout=19).dependency_tree(
        workspace(project),
        output_file,
    )

    assert result.execution.status is ExecutionStatus.PASS
    assert result.raw_output == tree
    assert runner.calls == [
        (
            (
                "./mvnw",
                "-B",
                "dependency:tree",
                f"-DoutputFile={output_file.resolve()}",
                "-DappendOutput=true",
            ),
            project.resolve(),
            19,
        )
    ]


def test_dependency_tree_uses_system_maven_and_preserves_failure(tmp_path: Path) -> None:
    output_file = tmp_path / "tree.txt"
    runner = RecordingRunner(exit_code=1)

    result = MavenExecutor(runner=runner).dependency_tree(
        workspace(tmp_path),
        output_file,
    )

    assert result.execution.status is ExecutionStatus.FAIL
    assert result.raw_output == ""
    assert runner.calls[0][0][:3] == ("mvn", "-B", "dependency:tree")


def test_dependency_tree_success_without_output_is_execution_error(tmp_path: Path) -> None:
    result = MavenExecutor(runner=RecordingRunner()).dependency_tree(
        workspace(tmp_path),
        tmp_path / "missing-tree.txt",
    )

    assert result.execution.status is ExecutionStatus.ERROR
    assert "produced no dependency tree" in (result.execution.detail or "")


def test_dependency_tree_timeout_is_distinct_from_maven_failure(tmp_path: Path) -> None:
    result = MavenExecutor(
        runner=RecordingRunner(exit_code=None, timed_out=True)
    ).dependency_tree(
        workspace(tmp_path),
        tmp_path / "tree.txt",
    )

    assert result.execution.status is ExecutionStatus.TIMEOUT
    assert result.execution.commands[0].timed_out


def test_dependency_tree_start_failure_is_execution_error(tmp_path: Path) -> None:
    error = CommandExecutionError(
        ("mvn", "-B", "dependency:tree"),
        tmp_path,
        FileNotFoundError("mvn missing"),
    )

    result = MavenExecutor(runner=RecordingRunner(error=error)).dependency_tree(
        workspace(tmp_path),
        tmp_path / "tree.txt",
    )

    assert result.execution.status is ExecutionStatus.ERROR
    assert result.execution.commands == ()
    assert "mvn missing" in (result.execution.detail or "")


def test_artifact_list_uses_absolute_filename_output_without_pom_edits(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "mvnw").write_text("wrapper", encoding="utf-8")
    output_file = tmp_path / "state" / "artifacts.txt"
    output_file.parent.mkdir()
    raw = "org.example:parser:jar:1.0:compile:/cache/parser.jar\n"
    runner = RecordingRunner(tree_output=raw)

    result = MavenExecutor(runner=runner, timeout=23).artifact_list(
        workspace(project), output_file
    )

    assert result.execution.status is ExecutionStatus.PASS
    assert result.raw_output == raw
    assert runner.calls == [
        (
            (
                "./mvnw",
                "-B",
                "dependency:list",
                f"-DoutputFile={output_file.resolve()}",
                "-DoutputAbsoluteArtifactFilename=true",
                "-DappendOutput=true",
            ),
            project.resolve(),
            23,
        )
    ]


def test_artifact_list_missing_tool_is_execution_error(tmp_path: Path) -> None:
    error = CommandExecutionError(
        ("mvn", "-B", "dependency:list"),
        tmp_path,
        FileNotFoundError("mvn missing"),
    )

    result = MavenExecutor(runner=RecordingRunner(error=error)).artifact_list(
        workspace(tmp_path), tmp_path / "artifacts.txt"
    )

    assert result.execution.status is ExecutionStatus.ERROR
    assert "mvn missing" in (result.execution.detail or "")
