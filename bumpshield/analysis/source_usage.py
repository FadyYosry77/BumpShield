"""Safe deterministic discovery of Java source usages for migration planning."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from bumpshield.models import (
    AffectedLocationKind,
    AffectedSourceLocation,
    ApiEvidence,
    EvidenceStrength,
    MigrationKind,
    RootCauseHypothesis,
    SourceFileKind,
)

LOGGER = logging.getLogger(__name__)
_EXCLUDED_DIRECTORIES = {".git", ".bumpshield", "target"}
_PRODUCTION_ROOT = ("src", "main", "java")
_TEST_ROOT = ("src", "test", "java")


class SourceUsageFinder:
    """Find conservative lexical usages without leaving one isolated workspace."""

    def find(
        self,
        workspace: Path,
        hypothesis: RootCauseHypothesis,
        api_evidence: ApiEvidence,
        migration_kind: MigrationKind,
    ) -> tuple[AffectedSourceLocation, ...]:
        root = Path(workspace).resolve()
        found: dict[tuple[Path, int], AffectedSourceLocation] = {}
        primary = self._primary_location(root, hypothesis)
        if primary is not None:
            found[(primary.file, primary.line)] = primary

        for relative, source in self._java_sources(root):
            for line_number, line in enumerate(source.splitlines(), start=1):
                location_kind = _matching_location_kind(
                    line,
                    migration_kind,
                    api_evidence.class_name,
                    _member_name(api_evidence.failure_symbol),
                )
                if location_kind is None:
                    continue
                key = (relative, line_number)
                if key in found:
                    continue
                found[key] = AffectedSourceLocation(
                    file=relative,
                    line=line_number,
                    kind=location_kind,
                    source_kind=_source_file_kind(relative),
                    evidence_strength=(
                        EvidenceStrength.STRONG
                        if location_kind is AffectedLocationKind.EXACT_IMPORT
                        else EvidenceStrength.MODERATE
                    ),
                    excerpt=line,
                )

        return tuple(sorted(found.values(), key=_location_sort_key))

    def _primary_location(
        self,
        root: Path,
        hypothesis: RootCauseHypothesis,
    ) -> AffectedSourceLocation | None:
        failure = hypothesis.failure
        if failure is None or failure.file is None or failure.line is None:
            return None
        relative = Path(failure.file)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        candidate = _safe_java_file(root / relative, root)
        if candidate is None:
            return None
        try:
            lines = candidate.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError as error:
            LOGGER.warning("Could not read primary migration source %s: %s", candidate, error)
            return None
        if failure.line > len(lines):
            return None
        return AffectedSourceLocation(
            file=relative,
            line=failure.line,
            kind=AffectedLocationKind.PRIMARY_FAILURE,
            source_kind=_source_file_kind(relative),
            evidence_strength=EvidenceStrength.VERY_STRONG,
            excerpt=lines[failure.line - 1],
        )

    @staticmethod
    def _java_sources(root: Path) -> tuple[tuple[Path, str], ...]:
        sources: list[tuple[Path, str]] = []
        for current_text, directories, files in os.walk(root, followlinks=False):
            current = Path(current_text)
            directories[:] = sorted(
                name
                for name in directories
                if name not in _EXCLUDED_DIRECTORIES
                and not (current / name).is_symlink()
            )
            relative_directory = current.relative_to(root)
            if _source_file_kind_or_none(relative_directory) is None:
                continue
            for filename in sorted(files):
                if not filename.endswith(".java"):
                    continue
                candidate = current / filename
                if candidate.is_symlink():
                    continue
                safe = _safe_java_file(candidate, root)
                if safe is None:
                    continue
                try:
                    text = safe.read_text(encoding="utf-8", errors="replace")
                except OSError as error:
                    LOGGER.warning("Could not read migration source %s: %s", safe, error)
                    continue
                sources.append((safe.relative_to(root), text))
        return tuple(sources)


def _matching_location_kind(
    line: str,
    migration_kind: MigrationKind,
    class_name: str,
    member_name: str | None,
) -> AffectedLocationKind | None:
    if migration_kind in {
        MigrationKind.REMOVED_METHOD,
        MigrationKind.CHANGED_METHOD_SIGNATURE,
    }:
        if member_name and re.search(rf"(?:\.|\b){re.escape(member_name)}\s*\(", line):
            return AffectedLocationKind.POTENTIAL_CALL_SITE
        return None

    if migration_kind is MigrationKind.REMOVED_PACKAGE:
        if re.match(
            rf"^\s*import\s+(?:static\s+)?{re.escape(class_name)}(?:\.|;)",
            line,
        ):
            return AffectedLocationKind.EXACT_IMPORT
        return None

    if migration_kind in {
        MigrationKind.REMOVED_CLASS,
        MigrationKind.REMOVED_DEPENDENCY,
    }:
        simple_name = class_name.rsplit(".", 1)[-1]
        if re.match(
            rf"^\s*import\s+(?:static\s+)?{re.escape(class_name)}(?:\.[\w*]+)?\s*;",
            line,
        ):
            return AffectedLocationKind.EXACT_IMPORT
        if re.search(rf"\b{re.escape(simple_name)}\b", line):
            return AffectedLocationKind.POTENTIAL_TYPE_REFERENCE
    return None


def _member_name(symbol: str | None) -> str | None:
    if not symbol:
        return None
    cleaned = re.sub(r"^(?:method|class|variable)\s+", "", symbol).strip()
    name = cleaned.split("(", 1)[0].rsplit(".", 1)[-1]
    return name or None


def _source_file_kind(path: Path) -> SourceFileKind:
    return _source_file_kind_or_none(path) or SourceFileKind.GENERATED_SOURCE


def _source_file_kind_or_none(path: Path) -> SourceFileKind | None:
    parts = path.parts
    if _contains_parts(parts, _PRODUCTION_ROOT):
        return SourceFileKind.PRODUCTION_SOURCE
    if _contains_parts(parts, _TEST_ROOT):
        return SourceFileKind.TEST_SOURCE
    if "target" in parts and "generated-sources" in parts:
        return SourceFileKind.GENERATED_SOURCE
    return None


def _contains_parts(parts: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    width = len(pattern)
    return any(parts[index : index + width] == pattern for index in range(len(parts) - width + 1))


def _safe_java_file(candidate: Path, root: Path) -> Path | None:
    try:
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve()
        resolved.relative_to(root)
        return resolved if resolved.is_file() and resolved.suffix == ".java" else None
    except (OSError, ValueError):
        return None


def _location_sort_key(location: AffectedSourceLocation) -> tuple[object, ...]:
    priority = 0 if location.kind is AffectedLocationKind.PRIMARY_FAILURE else 1
    return priority, str(location.file), location.line, location.kind.value
