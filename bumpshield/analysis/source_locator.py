"""Safe Java source localization and bounded context extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path

from bumpshield.config import SOURCE_CONTEXT_RADIUS
from bumpshield.models import FailureSignal, SourceContext, SourceLine, StackFrame

LOGGER = logging.getLogger(__name__)

_SOURCE_ROOTS = (
    Path("src/main/java"),
    Path("src/test/java"),
    Path("target/generated-sources"),
)
_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;")
_IMPORT = re.compile(r"^\s*import\s+((?:static\s+)?[\w.*]+)\s*;")


class SourceLocator:
    """Map reported Java paths only to files inside one workspace."""

    def __init__(self, context_radius: int = SOURCE_CONTEXT_RADIUS) -> None:
        if context_radius < 0:
            raise ValueError("context_radius must not be negative")
        self.context_radius = context_radius

    def localize(self, failure: FailureSignal, workspace: Path) -> FailureSignal:
        """Return failure with repository-relative file when mapping is unique."""
        root = Path(workspace).resolve()
        if failure.reported_file:
            localized = self._localize_reported(failure.reported_file, root)
            if localized is not None:
                return replace(failure, file=localized)

        for frame in failure.stack_frames:
            localized = self._localize_frame(frame, root)
            if localized is not None:
                return replace(
                    failure,
                    file=localized,
                    line=frame.line,
                    reported_file=frame.file_name,
                )
        return replace(failure, file=None)

    def context_for(
        self,
        failure: FailureSignal,
        workspace: Path,
    ) -> SourceContext | None:
        """Read a bounded one-based window for a safely localized failure."""
        if failure.file is None or failure.line is None:
            return None
        root = Path(workspace).resolve()
        candidate = self._safe_file(root / failure.file, root)
        if candidate is None or candidate.suffix != ".java":
            return None
        try:
            source_lines = candidate.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError as error:
            LOGGER.warning("Could not read localized source %s: %s", candidate, error)
            return None
        if failure.line > len(source_lines):
            return None

        start = max(1, failure.line - self.context_radius)
        end = min(len(source_lines), failure.line + self.context_radius)
        lines = tuple(
            SourceLine(number=number, text=source_lines[number - 1])
            for number in range(start, end + 1)
        )
        package = next(
            (
                match.group(1)
                for line in source_lines
                if (match := _PACKAGE.match(line)) is not None
            ),
            None,
        )
        imports = tuple(
            match.group(1)
            for line in source_lines
            if (match := _IMPORT.match(line)) is not None
        )
        return SourceContext(
            file=failure.file,
            start_line=start,
            end_line=end,
            focus_line=failure.line,
            lines=lines,
            package=package,
            imports=imports,
        )

    def _localize_reported(self, reported_file: str, root: Path) -> Path | None:
        reported = Path(reported_file)
        if not reported.is_absolute() and ".." in reported.parts:
            return None

        if reported.is_absolute():
            direct = self._safe_file(reported, root)
            if direct is not None:
                return direct.relative_to(root)
            suffix = _recognized_source_suffix(reported)
            if suffix is None:
                return None
            return self._find_unique_suffix(suffix, root)

        direct = self._unique_relative((root / reported,), root)
        if direct is not None:
            return direct
        suffix = _recognized_source_suffix(reported)
        if suffix is not None:
            direct = self._find_unique_suffix(suffix, root)
            if direct is not None:
                return direct
        if len(reported.parts) == 1 and reported.suffix == ".java":
            return self._find_unique_name(reported.name, root)
        return None

    def _localize_frame(self, frame: StackFrame, root: Path) -> Path | None:
        top_level_class = frame.class_name.split("$", 1)[0]
        class_suffix = Path(*top_level_class.split(".")).with_suffix(".java")
        exact_candidates = tuple(
            root / source_root / class_suffix for source_root in _SOURCE_ROOTS
        )
        exact = self._unique_relative(exact_candidates, root)
        if exact is not None:
            return exact
        if "." not in top_level_class:
            return self._find_unique_name(frame.file_name, root)
        return None

    def _find_unique_suffix(self, suffix: Path, root: Path) -> Path | None:
        candidates: list[Path] = []
        try:
            possible_files = root.rglob(suffix.name)
            for candidate in possible_files:
                safe = self._safe_file(candidate, root)
                if safe is None:
                    continue
                relative = safe.relative_to(root)
                if relative.parts[-len(suffix.parts) :] == suffix.parts:
                    candidates.append(safe)
        except OSError:
            return None
        return self._unique_relative(tuple(candidates), root)

    def _find_unique_name(self, file_name: str, root: Path) -> Path | None:
        candidates: list[Path] = []
        for source_root in _SOURCE_ROOTS:
            directory = self._safe_directory(root / source_root, root)
            if directory is None:
                continue
            candidates.extend(directory.rglob(file_name))
        return self._unique_relative(tuple(candidates), root)

    def _unique_relative(
        self,
        candidates: tuple[Path, ...],
        root: Path,
    ) -> Path | None:
        resolved = {
            safe
            for candidate in candidates
            if (safe := self._safe_file(candidate, root)) is not None
        }
        if len(resolved) != 1:
            return None
        return resolved.pop().relative_to(root)

    @staticmethod
    def _safe_file(candidate: Path, root: Path) -> Path | None:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
            return resolved if resolved.is_file() else None
        except (OSError, ValueError):
            return None

    @staticmethod
    def _safe_directory(candidate: Path, root: Path) -> Path | None:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
            return resolved if resolved.is_dir() else None
        except (OSError, ValueError):
            return None


def _recognized_source_suffix(path: Path) -> Path | None:
    parts = path.parts
    patterns = (
        ("src", "main", "java"),
        ("src", "test", "java"),
        ("target", "generated-sources"),
    )
    for pattern in patterns:
        width = len(pattern)
        for index in range(len(parts) - width + 1):
            if parts[index : index + width] == pattern:
                return Path(*parts[index:])
    return None
