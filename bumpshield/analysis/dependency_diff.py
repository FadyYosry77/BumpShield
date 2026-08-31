"""Deterministic Maven dependency-tree parsing and revision comparison."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.execution.maven import MavenDependencyExecution, MavenExecutor
from bumpshield.models import (
    DependencyAnalysisResult,
    DependencyChange,
    DependencyChangeKind,
    DependencyCoordinate,
    DependencyDiff,
    DependencyKey,
    DependencyNode,
    DependencyRelationship,
    DependencyTreeCommandResult,
    DependencyTreeResult,
    ExecutionStatus,
    TargetDependencyResolution,
    TaskSpec,
    WorkspaceKind,
)
from bumpshield.repo.workspace import RepositoryWorkspace, WorkspaceError, WorkspaceManager
from bumpshield.run import (
    RunSetupError,
    generate_run_id,
    require_external_path,
    validate_task_repository,
)
from bumpshield.task_io import task_spec_to_dict

_LOG_PREFIX = re.compile(r"^\[(?:INFO|WARNING|ERROR|DEBUG)\]\s*")
_TREE_LINE = re.compile(r"^(?P<indent>(?:(?:\|  |   ))*)(?:\+-|\\-)\s+(?P<body>.+)$")
_OMITTED_MARKERS = ("omitted for conflict", "omitted for duplicate")


class DependencyTreeParseError(ValueError):
    """Raised when dependency output cannot be represented safely."""


class DependencyAnalysisError(RuntimeError):
    """Raised when dependency collection or persistence cannot complete."""


@dataclass(frozen=True, slots=True)
class ParsedDependencyTree:
    """Parser output before it is tied to a Git revision."""

    nodes: tuple[DependencyNode, ...]
    project: DependencyKey
    warnings: tuple[str, ...] = ()


class DependencyTreeParser:
    """Parse the standard text output of Maven Dependency Plugin."""

    def parse(self, text: str) -> ParsedDependencyTree:
        """Return active resolved nodes, rejecting ambiguous reactor output."""
        nodes: list[DependencyNode] = []
        warnings: list[str] = []
        projects: list[DependencyKey] = []
        parent_at_depth: dict[int, DependencyKey] = {}
        nodes_by_key: dict[DependencyKey, DependencyNode] = {}

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = _LOG_PREFIX.sub("", raw_line).rstrip()
            if not line:
                continue

            tree_match = _TREE_LINE.match(line)
            if tree_match is None:
                project = _parse_project_coordinate(line)
                if project is not None:
                    projects.append(project)
                    parent_at_depth.clear()
                continue

            body = tree_match.group("body").strip()
            depth = len(tree_match.group("indent")) // 3 + 1
            if any(marker in body.lower() for marker in _OMITTED_MARKERS):
                for stale_depth in tuple(parent_at_depth):
                    if stale_depth >= depth:
                        del parent_at_depth[stale_depth]
                continue

            coordinate, scope = _parse_dependency_coordinate(body, line_number)
            parent = None
            if depth > 1:
                parent = parent_at_depth.get(depth - 1)
                if parent is None:
                    raise DependencyTreeParseError(
                        f"line {line_number}: dependency at depth {depth} has no active parent"
                    )
            relationship = (
                DependencyRelationship.DIRECT
                if depth == 1
                else DependencyRelationship.TRANSITIVE
            )
            node = DependencyNode(
                coordinate=coordinate,
                relationship=relationship,
                scope=scope,
                depth=depth,
                parent=parent,
            )
            existing = nodes_by_key.get(node.key)
            if existing is not None:
                if (
                    existing.coordinate.version != node.coordinate.version
                    or existing.scope != node.scope
                ):
                    raise DependencyTreeParseError(
                        f"line {line_number}: conflicting active entries for "
                        f"{_key_text(node.key)}"
                    )
                warnings.append(
                    f"line {line_number}: duplicate active entry ignored for "
                    f"{_key_text(node.key)}"
                )
            else:
                nodes.append(node)
                nodes_by_key[node.key] = node

            parent_at_depth[depth] = node.key
            for stale_depth in tuple(parent_at_depth):
                if stale_depth > depth:
                    del parent_at_depth[stale_depth]

        if not projects:
            raise DependencyTreeParseError("no Maven project root found in dependency tree")
        if len(projects) > 1:
            raise DependencyTreeParseError(
                "multi-module dependency tree output contains multiple project roots; "
                "reactor analysis is not supported in Phase 2"
            )
        return ParsedDependencyTree(tuple(nodes), projects[0], tuple(warnings))


def compare_dependency_trees(
    before: tuple[DependencyNode, ...],
    after: tuple[DependencyNode, ...],
    task: TaskSpec,
) -> DependencyDiff:
    """Compare resolved sets by version-independent Maven identity."""
    before_by_key = _index_nodes(before, "base")
    after_by_key = _index_nodes(after, "updated")
    target_before = _find_target(before, task)
    target_after = _find_target(after, task)
    target_keys = {
        node.key for node in (target_before, target_after) if node is not None
    }
    changes: list[DependencyChange] = []

    for key in sorted(before_by_key.keys() | after_by_key.keys(), key=_key_sort_value):
        before_node = before_by_key.get(key)
        after_node = after_by_key.get(key)
        if before_node is None:
            kind = DependencyChangeKind.ADDED
        elif after_node is None:
            kind = DependencyChangeKind.REMOVED
        elif (
            before_node.coordinate.version != after_node.coordinate.version
            or before_node.scope != after_node.scope
        ):
            kind = DependencyChangeKind.UPDATED
        else:
            kind = DependencyChangeKind.UNCHANGED

        relationship_node = after_node or before_node
        assert relationship_node is not None
        changes.append(
            DependencyChange(
                kind=kind,
                relationship=relationship_node.relationship,
                before=before_node.coordinate if before_node else None,
                after=after_node.coordinate if after_node else None,
                before_scope=before_node.scope if before_node else None,
                after_scope=after_node.scope if after_node else None,
                is_target=key in target_keys,
            )
        )

    target = task.target_dependency
    return DependencyDiff(
        changes=tuple(changes),
        target=TargetDependencyResolution(
            group_id=target.group_id,
            artifact_id=target.artifact_id,
            expected_base_version=target.old_version,
            resolved_base_version=(
                target_before.coordinate.version if target_before else None
            ),
            expected_updated_version=target.new_version,
            resolved_updated_version=(
                target_after.coordinate.version if target_after else None
            ),
        ),
    )


class DependencyAnalyzer:
    """Collect, parse, compare, and persist dependency evidence."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        maven: MavenDependencyExecution | None = None,
        config: BumpShieldConfig | None = None,
        parser: DependencyTreeParser | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.maven = maven if maven is not None else MavenExecutor(runner=self.runner)
        self.config = config if config is not None else BumpShieldConfig()
        self.parser = parser or DependencyTreeParser()

    def analyze(
        self,
        task: TaskSpec,
        run_id: str | None = None,
    ) -> DependencyAnalysisResult:
        """Analyze both revisions without running the Maven test lifecycle."""
        try:
            repository, repository_root = validate_task_repository(task, self.runner)
            effective_run_id = run_id or generate_run_id()
            artifact_path = self.config.run_directory(effective_run_id).resolve()
            require_external_path(artifact_path, repository_root)
            artifacts = DependencyArtifacts.create(artifact_path)
            artifacts.write_task(task)
        except RunSetupError as error:
            raise DependencyAnalysisError(str(error)) from error

        try:
            with WorkspaceManager(repository, effective_run_id) as workspaces:
                base_workspace = workspaces.create(task.base_commit, WorkspaceKind.BASE)
                base = self.collect_workspace(
                    base_workspace,
                    artifacts.base_tree_path,
                )
                artifacts.write_tree_result("dependencies-before.json", base)

                updated_workspace = workspaces.create(
                    task.updated_commit,
                    WorkspaceKind.UPDATED,
                )
                updated = self.collect_workspace(
                    updated_workspace,
                    artifacts.updated_tree_path,
                )
                artifacts.write_tree_result("dependencies-after.json", updated)
        except WorkspaceError as error:
            raise DependencyAnalysisError(str(error)) from error

        diff = compare_dependency_trees(base.nodes, updated.nodes, task)
        artifacts.write_diff(effective_run_id, diff)
        return DependencyAnalysisResult(
            run_id=effective_run_id,
            task=task,
            artifact_directory=artifacts.path,
            base=base,
            updated=updated,
            diff=diff,
        )

    def collect_workspace(
        self,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> DependencyTreeResult:
        """Collect and parse one workspace for reuse by later analysis phases."""
        collection = self.maven.dependency_tree(workspace, output_file)
        _preserve_failed_command_output(collection)
        if collection.execution.status is not ExecutionStatus.PASS:
            detail = collection.execution.detail or "Maven dependency tree command failed"
            raise DependencyAnalysisError(
                f"dependency collection for {workspace.kind.value.lower()} "
                f"ended with {collection.execution.status.value}: {detail}"
            )
        try:
            parsed = self.parser.parse(collection.raw_output)
        except DependencyTreeParseError as error:
            raise DependencyAnalysisError(
                f"could not parse {workspace.kind.value.lower()} dependency tree: {error}"
            ) from error
        return DependencyTreeResult(
            commit=workspace.commit,
            execution=collection.execution,
            nodes=parsed.nodes,
            raw_output_path=collection.output_file,
            parse_warnings=parsed.warnings,
        )


class DependencyArtifacts:
    """Single owner for Phase 2 dependency artifact formats."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def create(cls, path: Path) -> DependencyArtifacts:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            raise DependencyAnalysisError(
                f"could not create run directory {path}: {error}"
            ) from error
        return cls(path)

    @property
    def base_tree_path(self) -> Path:
        return self.path / "base-dependency-tree.txt"

    @property
    def updated_tree_path(self) -> Path:
        return self.path / "updated-dependency-tree.txt"

    def write_task(self, task: TaskSpec) -> None:
        self._write_json("task.json", task_spec_to_dict(task))

    def write_tree_result(
        self,
        filename: str,
        result: DependencyTreeResult,
    ) -> None:
        self._write_json(
            filename,
            {
                "commit": result.commit,
                "parse_warnings": list(result.parse_warnings),
                "dependencies": [dependency_node_to_dict(node) for node in result.nodes],
            },
        )

    def write_diff(self, run_id: str, diff: DependencyDiff) -> None:
        self._write_json("dependency-diff.json", dependency_diff_to_dict(run_id, diff))

    def _write_json(self, filename: str, data: dict[str, object]) -> None:
        path = self.path / filename
        try:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        except OSError as error:
            raise DependencyAnalysisError(f"could not write artifact {path}: {error}") from error


def dependency_diff_to_dict(run_id: str, diff: DependencyDiff) -> dict[str, object]:
    """Return canonical JSON-compatible dependency diff data."""
    target = diff.target
    counts = {
        kind.value.lower(): len(diff.of_kind(kind))
        for kind in DependencyChangeKind
    }
    return {
        "run_id": run_id,
        "target": (
            {
                "group_id": target.group_id,
                "artifact_id": target.artifact_id,
                "expected_base_version": target.expected_base_version,
                "resolved_base_version": target.resolved_base_version,
                "expected_updated_version": target.expected_updated_version,
                "resolved_updated_version": target.resolved_updated_version,
                "matched": target.matched,
            }
            if target
            else None
        ),
        "counts": counts,
        "changes": [_change_to_dict(change) for change in diff.changes],
    }


def _parse_project_coordinate(line: str) -> DependencyKey | None:
    clean = line.partition(" (")[0].strip()
    parts = clean.split(":")
    if len(parts) not in {4, 5} or any(not part for part in parts):
        return None
    group_id, artifact_id, dependency_type = parts[:3]
    classifier = parts[3] if len(parts) == 5 else None
    return DependencyKey(group_id, artifact_id, dependency_type, classifier)


def _parse_dependency_coordinate(
    body: str,
    line_number: int,
) -> tuple[DependencyCoordinate, str]:
    clean = body.partition(" (")[0].strip()
    parts = clean.split(":")
    if len(parts) == 5:
        group_id, artifact_id, dependency_type, version, scope = parts
        classifier = None
    elif len(parts) == 6:
        group_id, artifact_id, dependency_type, classifier, version, scope = parts
    else:
        raise DependencyTreeParseError(
            f"line {line_number}: unsupported dependency coordinate: {body}"
        )
    if any(not part.strip() for part in parts):
        raise DependencyTreeParseError(
            f"line {line_number}: dependency coordinate contains an empty field"
        )
    return (
        DependencyCoordinate(
            group_id=group_id,
            artifact_id=artifact_id,
            version=version,
            type=dependency_type,
            classifier=classifier,
        ),
        scope,
    )


def _index_nodes(
    nodes: tuple[DependencyNode, ...],
    revision: str,
) -> dict[DependencyKey, DependencyNode]:
    indexed: dict[DependencyKey, DependencyNode] = {}
    for node in nodes:
        if node.key in indexed:
            raise DependencyAnalysisError(
                f"duplicate dependency identity in {revision} tree: {_key_text(node.key)}"
            )
        indexed[node.key] = node
    return indexed


def _find_target(nodes: tuple[DependencyNode, ...], task: TaskSpec) -> DependencyNode | None:
    target = task.target_dependency
    matches = [
        node
        for node in nodes
        if node.coordinate.group_id == target.group_id
        and node.coordinate.artifact_id == target.artifact_id
    ]
    canonical = [
        node
        for node in matches
        if node.coordinate.type == "jar" and node.coordinate.classifier is None
    ]
    if len(canonical) == 1:
        return canonical[0]
    if not canonical and len(matches) <= 1:
        return matches[0] if matches else None
    raise DependencyAnalysisError(
        f"target dependency is ambiguous in resolved tree: "
        f"{target.group_id}:{target.artifact_id}"
    )


def _preserve_failed_command_output(collection: DependencyTreeCommandResult) -> None:
    if collection.output_file.exists():
        return
    sections: list[str] = []
    for command in collection.execution.commands:
        sections.extend((command.stdout, command.stderr))
    if collection.execution.detail:
        sections.append(collection.execution.detail)
    try:
        collection.output_file.write_text("".join(sections), encoding="utf-8")
    except OSError as error:
        raise DependencyAnalysisError(
            f"could not preserve Maven output {collection.output_file}: {error}"
        ) from error


def dependency_node_to_dict(node: DependencyNode) -> dict[str, object]:
    """Return canonical JSON-compatible dependency node."""
    coordinate = node.coordinate
    return {
        "group_id": coordinate.group_id,
        "artifact_id": coordinate.artifact_id,
        "type": coordinate.type,
        "classifier": coordinate.classifier,
        "version": coordinate.version,
        "scope": node.scope,
        "depth": node.depth,
        "relationship": node.relationship.value,
        "parent": _key_to_dict(node.parent) if node.parent else None,
    }


def _change_to_dict(change: DependencyChange) -> dict[str, object]:
    return {
        "kind": change.kind.value,
        "relationship": change.relationship.value,
        "is_target": change.is_target,
        "before": _coordinate_to_dict(change.before, change.before_scope),
        "after": _coordinate_to_dict(change.after, change.after_scope),
    }


def _coordinate_to_dict(
    coordinate: DependencyCoordinate | None,
    scope: str | None,
) -> dict[str, object] | None:
    if coordinate is None:
        return None
    return {
        "group_id": coordinate.group_id,
        "artifact_id": coordinate.artifact_id,
        "type": coordinate.type,
        "classifier": coordinate.classifier,
        "version": coordinate.version,
        "scope": scope,
    }


def _key_to_dict(key: DependencyKey) -> dict[str, object]:
    return {
        "group_id": key.group_id,
        "artifact_id": key.artifact_id,
        "type": key.type,
        "classifier": key.classifier,
    }


def _key_text(key: DependencyKey) -> str:
    classifier = f":{key.classifier}" if key.classifier else ""
    return f"{key.group_id}:{key.artifact_id}:{key.type}{classifier}"


def _key_sort_value(key: DependencyKey) -> tuple[str, str, str, str]:
    return key.group_id, key.artifact_id, key.type, key.classifier or ""
