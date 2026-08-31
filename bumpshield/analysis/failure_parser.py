"""Deterministic Maven/Javac/Surefire failure parsing and analysis."""

from __future__ import annotations

import json
import re
from pathlib import Path

from bumpshield.analysis.source_locator import SourceLocator
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.execution.maven import MavenExecution, MavenExecutor
from bumpshield.models import (
    ExecutionResult,
    ExecutionStatus,
    FailureAnalysisResult,
    FailureAnalysisStatus,
    FailureCategory,
    FailureSignal,
    SourceContext,
    StackFrame,
    TaskSpec,
    WorkspaceKind,
)
from bumpshield.repo.workspace import WorkspaceError, WorkspaceManager
from bumpshield.run import (
    RunSetupError,
    execution_log_text,
    generate_run_id,
    require_external_path,
    validate_task_repository,
)
from bumpshield.task_io import task_spec_to_dict

_MAVEN_PREFIX = re.compile(r"^\s*\[(?:ERROR|WARNING|INFO|DEBUG)\]\s?")
_COMPILER_LOCATION = re.compile(
    r"^(?P<file>.+?\.java):\[(?P<line>\d+)(?:,(?P<column>\d+))?\]\s*(?P<message>.*)$"
)
_PACKAGE_NOT_FOUND = re.compile(r"package\s+([\w.]+)\s+does not exist", re.IGNORECASE)
_SIGNATURE_METHOD = re.compile(r"method\s+([^\s(]+)\s+in\s+(?:class|interface)", re.IGNORECASE)
_TEST_HEADER_DOT = re.compile(
    r"^(?P<class>[\w.$]+)\.(?P<method>[\w$<>\[\]-]+)\s+--\s+Time elapsed:.*$"
)
_TEST_HEADER_CLASSIC = re.compile(
    r"^(?P<method>[\w$<>\[\]-]+)\((?P<class>[\w.$]+)\)\s+Time elapsed:.*$"
)
_EXCEPTION = re.compile(
    r"^(?:Caused by:\s*)?(?P<type>[\w$]+(?:\.[\w$]+)*(?:Error|Exception|Failure))"
    r"(?::\s*(?P<message>.*))?$"
)
_STACK_FRAME = re.compile(
    r"^at\s+(?P<class>[\w.$]+)\.(?P<method>[^.(]+)"
    r"\((?P<file>[^():]+\.java):(?P<line>\d+)\)$"
)
_TEST_SUMMARY = re.compile(
    r"Tests run:\s*(?P<tests>\d+),\s*Failures:\s*(?P<failures>\d+),"
    r"\s*Errors:\s*(?P<errors>\d+),\s*Skipped:\s*(?P<skipped>\d+)",
    re.IGNORECASE,
)
_BLOCK_STOP_PREFIXES = (
    "BUILD FAILURE",
    "Failed to execute goal",
    "Total time:",
    "Finished at:",
    "-> [Help",
)
_MAX_DIAGNOSTIC_LINES = 12
_MAX_TEST_BLOCK_LINES = 80
_MAX_STACK_FRAMES = 20
_FRAMEWORK_PREFIXES = (
    "java.",
    "javax.",
    "jdk.",
    "sun.",
    "org.junit.",
    "org.opentest4j.",
    "org.apache.maven.",
    "org.codehaus.plexus.",
    "org.surefire.",
)


class FailureAnalysisError(RuntimeError):
    """Raised when failure-analysis infrastructure cannot continue."""


class FailureParser:
    """Parse evidence-backed compiler and test failures without filesystem access."""

    def parse(self, execution: ExecutionResult) -> tuple[FailureSignal, ...]:
        """Parse stdout then stderr for each command and deduplicate in order."""
        parsed: list[FailureSignal] = []
        for command in execution.commands:
            parsed.extend(self.parse_text(command.stdout))
            parsed.extend(self.parse_text(command.stderr))
        return _deduplicate(parsed)

    def parse_text(self, text: str) -> tuple[FailureSignal, ...]:
        """Parse one captured stream while retaining first-appearance order."""
        raw_lines = text.splitlines()
        lines = [_clean_line(line) for line in raw_lines]
        events = self._compiler_events(raw_lines, lines)
        test_events = self._test_events(raw_lines, lines)
        events.extend(test_events)
        if not test_events:
            events.extend(self._summary_events(raw_lines, lines))
        events.sort(key=lambda event: event[0])
        return _deduplicate([signal for _, signal in events])

    def _compiler_events(
        self,
        raw_lines: list[str],
        lines: list[str],
    ) -> list[tuple[int, FailureSignal]]:
        events: list[tuple[int, FailureSignal]] = []
        for index, line in enumerate(lines):
            match = _COMPILER_LOCATION.match(line)
            if match is None:
                continue
            block_end = _diagnostic_end(index, lines)
            block = lines[index:block_end]
            raw_block = raw_lines[index:block_end]
            events.append((index, _compiler_signal(match, block, raw_block)))
        return events

    def _test_events(
        self,
        raw_lines: list[str],
        lines: list[str],
    ) -> list[tuple[int, FailureSignal]]:
        events: list[tuple[int, FailureSignal]] = []
        for index, line in enumerate(lines):
            header = _TEST_HEADER_DOT.match(line) or _TEST_HEADER_CLASSIC.match(line)
            if header is None:
                continue
            end = min(len(lines), index + _MAX_TEST_BLOCK_LINES)
            for candidate_index in range(index + 1, end):
                if (
                    _TEST_HEADER_DOT.match(lines[candidate_index])
                    or _TEST_HEADER_CLASSIC.match(lines[candidate_index])
                    or _COMPILER_LOCATION.match(lines[candidate_index])
                    or lines[candidate_index].startswith("Results:")
                ):
                    end = candidate_index
                    break
            events.append(
                (
                    index,
                    _test_signal(
                        header.group("class"),
                        header.group("method"),
                        lines[index:end],
                        raw_lines[index:end],
                    ),
                )
            )
        return events

    def _summary_events(
        self,
        raw_lines: list[str],
        lines: list[str],
    ) -> list[tuple[int, FailureSignal]]:
        for index, line in enumerate(lines):
            match = _TEST_SUMMARY.search(line)
            if match and (
                int(match.group("failures")) > 0 or int(match.group("errors")) > 0
            ):
                return [
                    (
                        index,
                        FailureSignal(
                            category=FailureCategory.TEST_FAILURE,
                            message=_normalize_space(match.group(0)),
                            raw_excerpt=raw_lines[index],
                        ),
                    )
                ]
        return []


class FailureAnalyzer:
    """Execute updated revision, parse failures, localize source, persist evidence."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        maven: MavenExecution | None = None,
        config: BumpShieldConfig | None = None,
        parser: FailureParser | None = None,
        locator: SourceLocator | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.maven = maven if maven is not None else MavenExecutor(runner=self.runner)
        self.config = config if config is not None else BumpShieldConfig()
        self.parser = parser or FailureParser()
        self.locator = locator or SourceLocator()

    def analyze(
        self,
        task: TaskSpec,
        run_id: str | None = None,
    ) -> FailureAnalysisResult:
        """Analyze only updated revision in a detached temporary worktree."""
        try:
            repository, repository_root = validate_task_repository(task, self.runner)
            effective_run_id = run_id or generate_run_id()
            artifact_path = self.config.run_directory(effective_run_id).resolve()
            require_external_path(artifact_path, repository_root)
        except RunSetupError as error:
            raise FailureAnalysisError(str(error)) from error

        artifacts = FailureArtifacts.create(artifact_path)
        artifacts.write_task(task)
        try:
            with WorkspaceManager(repository, effective_run_id) as workspaces:
                workspace = workspaces.create(task.updated_commit, WorkspaceKind.UPDATED)
                execution, failures, contexts, status = self.analyze_workspace(workspace)
                artifacts.write_build_log(execution)
                result = FailureAnalysisResult(
                    run_id=effective_run_id,
                    task=task,
                    artifact_directory=artifacts.path,
                    status=status,
                    execution=execution,
                    failures=failures,
                    source_contexts=contexts,
                )
                artifacts.write_failures(result.failures)
                artifacts.write_contexts(result.source_contexts)
                artifacts.write_result(result)
        except WorkspaceError as error:
            raise FailureAnalysisError(str(error)) from error
        return result

    def analyze_workspace(
        self,
        workspace: RepositoryWorkspace,
    ) -> tuple[
        ExecutionResult,
        tuple[FailureSignal, ...],
        tuple[SourceContext, ...],
        FailureAnalysisStatus,
    ]:
        """Execute, parse, and localize one workspace without persisting artifacts."""
        execution = self.maven.execute(workspace)
        parsed = self.parser.parse(execution) if execution.status is ExecutionStatus.FAIL else ()
        failures = _deduplicate(
            [self.locator.localize(failure, workspace.path) for failure in parsed]
        )
        contexts: list[SourceContext] = []
        context_keys: set[tuple[Path, int]] = set()
        for failure in failures:
            context = self.locator.context_for(failure, workspace.path)
            if context is not None:
                key = (context.file, context.focus_line)
                if key not in context_keys:
                    context_keys.add(key)
                    contexts.append(context)
        return (
            execution,
            failures,
            tuple(contexts),
            classify_failure_analysis(execution, failures),
        )


def classify_failure_analysis(
    execution: ExecutionResult,
    failures: tuple[FailureSignal, ...],
) -> FailureAnalysisStatus:
    """Classify execution and localization without inventing failure evidence."""
    if execution.status is ExecutionStatus.PASS:
        return FailureAnalysisStatus.NO_FAILURE
    if execution.status is ExecutionStatus.TIMEOUT:
        return FailureAnalysisStatus.TIMEOUT
    if execution.status is ExecutionStatus.ERROR:
        return FailureAnalysisStatus.EXECUTION_ERROR
    localized = sum(failure.file is not None for failure in failures)
    if failures and localized == len(failures):
        return FailureAnalysisStatus.FAILURES_LOCALIZED
    if localized:
        return FailureAnalysisStatus.FAILURES_PARSED_PARTIALLY
    return FailureAnalysisStatus.FAILURE_UNLOCALIZED


class FailureArtifacts:
    """Single owner for Phase 3 artifact names and JSON schemas."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def create(cls, path: Path) -> FailureArtifacts:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise FailureAnalysisError(
                f"could not create run directory {path}: {error}"
            ) from error
        return cls(path)

    def write_task(self, task: TaskSpec) -> None:
        self._write_json("task.json", task_spec_to_dict(task))

    def write_build_log(self, execution: ExecutionResult) -> None:
        self._write_text("updated-build.log", execution_log_text(execution))

    def write_failures(self, failures: tuple[FailureSignal, ...]) -> None:
        self._write_json(
            "failures.json",
            [failure_to_dict(failure) for failure in failures],
        )

    def write_contexts(self, contexts: tuple[SourceContext, ...]) -> None:
        self._write_json(
            "source-contexts.json",
            [source_context_to_dict(context) for context in contexts],
        )

    def write_result(self, result: FailureAnalysisResult) -> None:
        command = result.execution.commands[-1] if result.execution.commands else None
        primary = result.primary_failure
        self._write_json(
            "failure-analysis.json",
            {
                "run_id": result.run_id,
                "status": result.status.value,
                "updated_commit": result.task.updated_commit,
                "execution": {
                    "status": result.execution.status.value,
                    "exit_code": command.exit_code if command else None,
                    "duration_seconds": command.duration_seconds if command else None,
                    "timed_out": command.timed_out if command else False,
                    "detail": result.execution.detail,
                },
                "failure_count": len(result.failures),
                "localized_count": sum(
                    failure.file is not None for failure in result.failures
                ),
                "primary_failure": failure_to_dict(primary) if primary else None,
            },
        )

    def _write_json(self, filename: str, data: object) -> None:
        self._write_text(filename, json.dumps(data, indent=2) + "\n")

    def _write_text(self, filename: str, text: str) -> None:
        path = self.path / filename
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as error:
            raise FailureAnalysisError(f"could not write artifact {path}: {error}") from error


def _compiler_signal(
    match: re.Match[str],
    block: list[str],
    raw_block: list[str],
) -> FailureSignal:
    initial = _clean_message(match.group("message"))
    joined = "\n".join(block)
    lower = joined.lower()
    symbol = _labeled_value(block, "symbol")
    if symbol:
        symbol = re.sub(r"^(?:method|class|variable)\s+", "", symbol).strip()
    location = _labeled_value(block, "location")
    required = _labeled_value(block, "required")
    found = _labeled_value(block, "found")

    if "cannot find symbol" in lower:
        category = FailureCategory.MISSING_SYMBOL
        message = "cannot find symbol"
    elif "cannot be applied to given types" in lower:
        category = FailureCategory.METHOD_ARGUMENT_MISMATCH
        method = _SIGNATURE_METHOD.search(joined)
        symbol = symbol or (method.group(1) if method else None)
        message = initial or "method cannot be applied to given types"
    elif (package := _PACKAGE_NOT_FOUND.search(joined)) is not None:
        category = FailureCategory.PACKAGE_NOT_FOUND
        symbol = package.group(1)
        message = f"package {symbol} does not exist"
    elif "incompatible types" in lower:
        category = FailureCategory.INCOMPATIBLE_TYPES
        conversion = next(
            (line.strip() for line in block[1:] if "cannot be converted" in line),
            None,
        )
        message = (initial or "incompatible types").rstrip(":")
        if conversion and conversion not in message:
            message = f"{message}: {conversion}"
    else:
        category = FailureCategory.COMPILATION_ERROR_OTHER
        message = initial or _first_diagnostic_text(block[1:]) or "compiler error"

    return FailureSignal(
        category=category,
        message=_normalize_space(message),
        line=int(match.group("line")),
        column=int(match.group("column")) if match.group("column") else None,
        symbol=symbol,
        location=location,
        required=required,
        found=found,
        reported_file=match.group("file"),
        raw_excerpt="\n".join(raw_block),
    )


def _test_signal(
    test_class: str,
    test_method: str,
    block: list[str],
    raw_block: list[str],
) -> FailureSignal:
    exception_type: str | None = None
    exception_message: str | None = None
    for line in block[1:]:
        match = _EXCEPTION.match(line)
        if match:
            exception_type = match.group("type")
            exception_message = match.group("message")
            break
    frames = tuple(
        StackFrame(
            class_name=match.group("class"),
            method_name=match.group("method"),
            file_name=match.group("file"),
            line=int(match.group("line")),
        )
        for line in block
        if (match := _STACK_FRAME.match(line)) is not None
        and not match.group("class").startswith(_FRAMEWORK_PREFIXES)
    )[:_MAX_STACK_FRAMES]

    if exception_type and "assert" in exception_type.lower():
        category = FailureCategory.ASSERTION_FAILURE
    elif exception_type:
        category = FailureCategory.TEST_EXCEPTION
    else:
        category = FailureCategory.TEST_FAILURE
    message = exception_message or (
        exception_type if exception_type else f"{test_class}.{test_method} failed"
    )
    first_frame = frames[0] if frames else None
    excerpt_lines = raw_block[:_MAX_DIAGNOSTIC_LINES]
    return FailureSignal(
        category=category,
        message=_normalize_space(message),
        line=first_frame.line if first_frame else None,
        test_class=test_class,
        test_method=test_method,
        exception_type=exception_type,
        reported_file=first_frame.file_name if first_frame else None,
        stack_frames=frames,
        raw_excerpt="\n".join(excerpt_lines),
    )


def _diagnostic_end(index: int, lines: list[str]) -> int:
    end = min(len(lines), index + _MAX_DIAGNOSTIC_LINES)
    for candidate_index in range(index + 1, end):
        candidate = lines[candidate_index]
        if _COMPILER_LOCATION.match(candidate):
            return candidate_index
        if candidate.startswith(_BLOCK_STOP_PREFIXES):
            return candidate_index
    return end


def _labeled_value(lines: list[str], label: str) -> str | None:
    prefix = f"{label}:"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.lower().startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if value:
            return _normalize_space(value)
        if index + 1 < len(lines):
            continuation = lines[index + 1].strip()
            if continuation and ":" not in continuation.split(maxsplit=1)[0]:
                return _normalize_space(continuation)
    return None


def _first_diagnostic_text(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if stripped and not any(
            stripped.lower().startswith(f"{label}:")
            for label in ("symbol", "location", "required", "found", "reason")
        ):
            return stripped
    return None


def _clean_line(line: str) -> str:
    return _MAVEN_PREFIX.sub("", line).strip()


def _clean_message(message: str) -> str:
    cleaned = message.strip()
    if cleaned.lower().startswith("error:"):
        cleaned = cleaned[6:].strip()
    return cleaned


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _deduplicate(failures: list[FailureSignal]) -> tuple[FailureSignal, ...]:
    seen: set[tuple[object, ...]] = set()
    unique: list[FailureSignal] = []
    for failure in failures:
        key = (
            failure.category,
            failure.file if failure.file is not None else failure.reported_file,
            failure.line,
            failure.symbol,
            _normalize_space(failure.message).lower(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(failure)
    return tuple(unique)


def failure_to_dict(failure: FailureSignal) -> dict[str, object]:
    """Return canonical JSON-compatible failure evidence."""
    return {
        "category": failure.category.value,
        "file": str(failure.file) if failure.file else None,
        "line": failure.line,
        "column": failure.column,
        "symbol": failure.symbol,
        "location": failure.location,
        "required": failure.required,
        "found": failure.found,
        "test_class": failure.test_class,
        "test_method": failure.test_method,
        "exception_type": failure.exception_type,
        "stack_frames": [
            {
                "class": frame.class_name,
                "method": frame.method_name,
                "file": frame.file_name,
                "line": frame.line,
            }
            for frame in failure.stack_frames
        ],
        "message": failure.message,
        "raw_excerpt": failure.raw_excerpt,
    }


def source_context_to_dict(context: SourceContext) -> dict[str, object]:
    """Return canonical JSON-compatible source context."""
    return {
        "file": str(context.file),
        "focus_line": context.focus_line,
        "start_line": context.start_line,
        "end_line": context.end_line,
        "package": context.package,
        "imports": list(context.imports),
        "lines": [
            {"number": line.number, "text": line.text}
            for line in context.lines
        ],
    }
