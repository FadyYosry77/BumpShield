"""Git-ground-truth patch capture and pragmatic anti-cheating analysis."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from bumpshield.models import (
    MigrationPlan,
    PatchAnalysis,
    PatchBaseline,
    PatchScopeStatus,
    PatchStats,
    PlanScope,
    TestFileBaseline,
)
from bumpshield.repo.git import GitRepository, GitRepositoryError

_DISABLE_MARKER = re.compile(r"@(?:org\.junit\.[\w.]+\.)?(?:Disabled|Ignore)\b")
_SKIP_MARKER = re.compile(
    r"(?:maven\.test\.skip|skipTests|-DskipTests|"
    r"<skipTests>\s*true\s*</skipTests>|"
    r"<maven\.test\.skip>\s*true\s*</maven\.test\.skip>)",
    re.IGNORECASE,
)
_DUMMY_RETURN = re.compile(
    r"^\+\s*return\s+(?:null|false|true|0|\"\")\s*;\s*$"
)
_CONFIG_PATHS = {
    Path(".mvn/maven.config"),
    Path(".mvn/jvm.config"),
}
_MAX_CAPTURED_UNTRACKED_FILES = 1000


class PatchAnalysisError(RuntimeError):
    """Raised when Git patch evidence cannot be captured safely."""


class PatchAnalyzer:
    """Capture actual changes and compare protected deltas with Phase 6 plan."""

    def capture_baseline(self, workspace: Path) -> PatchBaseline:
        """Capture tests and skip configuration before provider modification."""
        root = Path(workspace).resolve()
        repository = GitRepository(root)
        try:
            tracked = repository.list_tracked_files()
        except GitRepositoryError as error:
            raise PatchAnalysisError(str(error)) from error
        tests = tuple(
            TestFileBaseline(path, _disable_count(_read_text(root, path)))
            for path in tracked
            if _is_test_java(path) and _safe_file(root, path) is not None
        )
        return PatchBaseline(
            test_files=tuple(sorted(tests, key=lambda item: str(item.file))),
            test_skip_markers=_skip_count(root, tracked),
        )

    def analyze(
        self,
        workspace: Path,
        baseline: PatchBaseline,
        plan: MigrationPlan,
    ) -> PatchAnalysis:
        """Return exact diff, statistics, scope, and delta-only safety findings."""
        root = Path(workspace).resolve()
        repository = GitRepository(root)
        try:
            untracked = _untracked_paths(repository.status_porcelain())
            untracked = tuple(path for path in untracked if not _is_generated(path))
            if len(untracked) > _MAX_CAPTURED_UNTRACKED_FILES:
                raise PatchAnalysisError(
                    "provider created too many untracked files for safe patch capture"
                )
            repository.mark_intent_to_add(untracked)
            patch = repository.diff_head()
            name_status = repository.diff_name_status()
            numstat = repository.diff_numstat()
            tracked_after = repository.list_tracked_files()
        except GitRepositoryError as error:
            raise PatchAnalysisError(str(error)) from error

        changed, added, deleted = _parse_name_status(name_status)
        line_stats = _parse_numstat(numstat)
        lines_added = sum(item[0] for item in line_stats.values())
        lines_removed = sum(item[1] for item in line_stats.values())
        stats = PatchStats(
            files_changed=len(changed),
            lines_added=lines_added,
            lines_removed=lines_removed,
            files_added=len(added),
            files_deleted=len(deleted),
        )

        baseline_tests = {item.file: item.disable_markers for item in baseline.test_files}
        current_paths = set(tracked_after) | set(untracked)
        deleted_tests = tuple(
            sorted(
                (path for path in baseline_tests if not (root / path).is_file()),
                key=str,
            )
        )
        newly_disabled = tuple(
            sorted(
                (
                    path
                    for path in current_paths
                    if _is_test_java(path)
                    and _disable_count(_read_text(root, path))
                    > baseline_tests.get(path, 0)
                ),
                key=str,
            )
        )
        skip_introduced = _skip_count(root, current_paths) > baseline.test_skip_markers

        allowed = set(plan.allowed_files)
        evidenced = {item.file for item in plan.affected_source_locations}
        changed_set = set(changed)
        expansions = tuple(sorted((changed_set - allowed) & evidenced, key=str))
        out_of_scope = tuple(
            sorted(changed_set - allowed - evidenced, key=str)
        )
        scope = (
            PatchScopeStatus.OUT_OF_SCOPE
            if out_of_scope
            else PatchScopeStatus.JUSTIFIED_EXPANSION
            if expansions
            else PatchScopeStatus.IN_SCOPE
        )
        manifests = tuple(
            path
            for path in changed
            if path.name == "pom.xml" or path in _CONFIG_PATHS
        )

        fatal: list[str] = []
        review: list[str] = []
        if deleted_tests:
            fatal.append("test files were deleted")
        if newly_disabled:
            fatal.append("test disablement markers were introduced")
        if skip_introduced:
            fatal.append("Maven test skipping was introduced")
        if out_of_scope:
            review.append("patch modifies files outside Phase 6 evidence")
        if manifests:
            review.append("dependency or Maven configuration was modified")
        if _is_broad_patch(plan.scope, len(changed)):
            review.append("patch is substantially broader than planned scope")
        if any(path.suffix == ".java" and not _is_test_java(path) for path in deleted):
            review.append("production Java source was deleted")
        if lines_removed > max(100, lines_added * 5 + 20):
            review.append("patch removes substantially more code than it adds")
        if any(_DUMMY_RETURN.match(line) for line in patch.splitlines()):
            review.append("patch introduces an obvious constant or dummy return")
        if _assertions_removed_without_replacement(patch):
            review.append("test assertions were removed without replacement")

        return PatchAnalysis(
            patch=patch,
            changed_files=changed,
            added_files=added,
            deleted_files=deleted,
            out_of_scope_files=out_of_scope,
            evidence_backed_expansions=expansions,
            deleted_test_files=deleted_tests,
            newly_disabled_test_files=newly_disabled,
            test_skip_introduced=skip_introduced,
            manifest_files_changed=manifests,
            scope_status=scope,
            stats=stats,
            fatal_issues=tuple(fatal),
            review_issues=tuple(review),
        )


def _parse_name_status(
    text: str,
) -> tuple[tuple[Path, ...], tuple[Path, ...], tuple[Path, ...]]:
    tokens = [token for token in text.split("\0") if token]
    changed: list[Path] = []
    added: list[Path] = []
    deleted: list[Path] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if "\t" in token:
            status, path_text = token.split("\t", 1)
            index += 1
        else:
            status = token
            index += 1
            if index >= len(tokens):
                raise PatchAnalysisError("malformed Git name-status output")
            path_text = tokens[index]
            index += 1
        if status.startswith(("R", "C")):
            if index >= len(tokens):
                raise PatchAnalysisError("malformed Git rename output")
            path_text = tokens[index]
            index += 1
        path = _safe_relative(path_text)
        changed.append(path)
        if status.startswith("A"):
            added.append(path)
        if status.startswith("D"):
            deleted.append(path)
    return (
        tuple(sorted(set(changed), key=str)),
        tuple(sorted(set(added), key=str)),
        tuple(sorted(set(deleted), key=str)),
    )


def _parse_numstat(text: str) -> dict[Path, tuple[int, int]]:
    result: dict[Path, tuple[int, int]] = {}
    for token in (value for value in text.split("\0") if value):
        fields = token.split("\t", 2)
        if len(fields) != 3:
            continue
        added_text, removed_text, path_text = fields
        if not path_text:
            continue
        path = _safe_relative(path_text)
        added = int(added_text) if added_text.isdigit() else 0
        removed = int(removed_text) if removed_text.isdigit() else 0
        result[path] = (added, removed)
    return result


def _untracked_paths(text: str) -> tuple[Path, ...]:
    return tuple(
        _safe_relative(token[3:])
        for token in text.split("\0")
        if token.startswith("?? ")
    )


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PatchAnalysisError(f"unsafe Git path: {value!r}")
    return path


def _safe_file(root: Path, relative: Path) -> Path | None:
    candidate = root / relative
    try:
        if candidate.is_symlink():
            return None
        resolved = candidate.resolve()
        resolved.relative_to(root)
        return resolved if resolved.is_file() else None
    except (OSError, ValueError):
        return None


def _read_text(root: Path, relative: Path) -> str:
    path = _safe_file(root, relative)
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _disable_count(text: str) -> int:
    return len(_DISABLE_MARKER.findall(text))


def _skip_count(root: Path, paths: Iterable[Path]) -> int:
    return sum(
        len(_SKIP_MARKER.findall(_read_text(root, path)))
        for path in paths
        if path.name == "pom.xml" or path in _CONFIG_PATHS
    )


def _is_test_java(path: Path) -> bool:
    parts = path.parts
    return path.suffix == ".java" and any(
        parts[index : index + 3] == ("src", "test", "java")
        for index in range(max(0, len(parts) - 2))
    )


def _is_generated(path: Path) -> bool:
    return "target" in path.parts or ".git" in path.parts


def _is_broad_patch(scope: PlanScope, files_changed: int) -> bool:
    thresholds = {
        PlanScope.SMALL: 10,
        PlanScope.MEDIUM: 15,
        PlanScope.LARGE: 30,
    }
    return files_changed > thresholds[scope]


def _assertions_removed_without_replacement(patch: str) -> bool:
    """Flag an obvious assertion-removal delta without pretending Java semantics."""
    removed = 0
    added = 0
    for line in patch.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if "assert" not in line.lower():
            continue
        if line.startswith("-"):
            removed += 1
        elif line.startswith("+"):
            added += 1
    return removed > 0 and added == 0
