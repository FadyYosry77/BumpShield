"""Deterministic Java type candidates from failure and source evidence."""

from __future__ import annotations

import re
from pathlib import Path

from bumpshield.models import (
    FailureCategory,
    FailureSignal,
    SourceContext,
    TypeCandidate,
    TypeCandidateOrigin,
)

_LOCATION_TYPE = re.compile(r"\b(?:of type|class|interface)\s+([\w$][\w.$]*)")
_QUALIFIED_TYPE = re.compile(r"\b(?:[a-z_]\w*\.)+[A-Z_$][\w$]*(?:\.[A-Z_$][\w$]*)*\b")
_PLATFORM_PREFIXES = ("java.", "javax.", "jdk.", "sun.")
_SOURCE_ROOT_MARKERS = (
    ("src", "main", "java"),
    ("src", "test", "java"),
)


class TypeCandidateExtractor:
    """Resolve focused type candidates without attempting full Java semantics."""

    def extract(
        self,
        failure: FailureSignal,
        context: SourceContext | None,
        project_root: Path,
    ) -> tuple[TypeCandidate, ...]:
        """Return ordered candidates, with concrete compiler evidence first."""
        root = Path(project_root).resolve()
        raw: list[tuple[str, TypeCandidateOrigin, bool]] = []

        if failure.category is FailureCategory.PACKAGE_NOT_FOUND and failure.symbol:
            raw.append(
                (failure.symbol, TypeCandidateOrigin.PACKAGE_REFERENCE, True)
            )
        location_type = _location_type(failure.location)
        if location_type and "." in location_type:
            raw.append((location_type, TypeCandidateOrigin.COMPILER_TYPE, False))

        for frame in failure.stack_frames:
            class_name = frame.class_name.replace("$", ".")
            raw.append((class_name, TypeCandidateOrigin.STACK_FRAME, False))

        simple_names = _simple_type_references(failure, location_type)
        if context is not None:
            project_candidates = [
                f"{context.package}.{name}"
                for name in simple_names
                if context.package
                and _project_type_exists(root, f"{context.package}.{name}")
            ]
            if project_candidates:
                raw.extend(
                    (name, TypeCandidateOrigin.COMPILER_TYPE, False)
                    for name in project_candidates
                )
            else:
                raw.extend(_import_candidates(context.imports, simple_names, failure))

        if not raw:
            for value in (failure.location, failure.required, failure.found, failure.message):
                if value:
                    raw.extend(
                        (name, TypeCandidateOrigin.COMPILER_TYPE, False)
                        for name in _QUALIFIED_TYPE.findall(value)
                    )

        candidates: list[TypeCandidate] = []
        seen: set[tuple[str, bool]] = set()
        for name, origin, is_package in raw:
            normalized = name.strip().replace("$", ".")
            if not normalized or _is_platform_type(normalized):
                continue
            key = (normalized, is_package)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                TypeCandidate(
                    name=normalized,
                    origin=origin,
                    project_owned=(
                        not is_package and _project_type_exists(root, normalized)
                    ),
                    is_package=is_package,
                )
            )
        return tuple(candidates)


def _location_type(location: str | None) -> str | None:
    if not location:
        return None
    match = _LOCATION_TYPE.search(location)
    return match.group(1) if match else None


def _simple_type_references(
    failure: FailureSignal,
    location_type: str | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if location_type and "." not in location_type and location_type[:1].isupper():
        values.append(location_type)
    if failure.symbol:
        symbol = failure.symbol.split("(", 1)[0].strip()
        if "." not in symbol and symbol[:1].isupper():
            values.append(symbol)
    for value in (failure.required, failure.found):
        if not value:
            continue
        for token in re.findall(r"\b[A-Z][\w$]*\b", value):
            values.append(token)
    return tuple(dict.fromkeys(values))


def _import_candidates(
    imports: tuple[str, ...],
    simple_names: tuple[str, ...],
    failure: FailureSignal,
) -> list[tuple[str, TypeCandidateOrigin, bool]]:
    candidates: list[tuple[str, TypeCandidateOrigin, bool]] = []
    symbol_name = failure.symbol.split("(", 1)[0] if failure.symbol else None
    for imported in imports:
        if imported.startswith("static "):
            target = imported.removeprefix("static ")
            owner, _, member = target.rpartition(".")
            if owner and (member == "*" or member == symbol_name):
                candidates.append((owner, TypeCandidateOrigin.STATIC_IMPORT, False))
            continue
        if imported.endswith(".*"):
            package = imported[:-2]
            candidates.extend(
                (f"{package}.{simple}", TypeCandidateOrigin.WILDCARD_IMPORT, False)
                for simple in simple_names
            )
            continue
        if imported.rsplit(".", 1)[-1] in simple_names:
            candidates.append((imported, TypeCandidateOrigin.EXPLICIT_IMPORT, False))
    return candidates


def _project_type_exists(root: Path, class_name: str) -> bool:
    top_level = class_name.split("$", 1)[0]
    suffix = Path(*top_level.split(".")).with_suffix(".java")
    try:
        for candidate in root.rglob(suffix.name):
            resolved = candidate.resolve()
            resolved.relative_to(root)
            relative_parts = resolved.relative_to(root).parts
            for marker in _SOURCE_ROOT_MARKERS:
                width = len(marker)
                for index in range(len(relative_parts) - width):
                    if relative_parts[index : index + width] == marker:
                        if relative_parts[index + width :] == suffix.parts:
                            return True
    except (OSError, ValueError):
        return False
    return False


def _is_platform_type(name: str) -> bool:
    return name.startswith(_PLATFORM_PREFIXES)
