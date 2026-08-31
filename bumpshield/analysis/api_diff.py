"""Targeted dependency-to-symbol attribution and Java API evidence collection."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from bumpshield.analysis.artifact_parser import ArtifactListParseError, ArtifactListParser
from bumpshield.analysis.dependency_diff import (
    DependencyAnalysisError,
    DependencyAnalyzer,
    compare_dependency_trees,
    dependency_diff_to_dict,
    dependency_node_to_dict,
)
from bumpshield.analysis.failure_parser import (
    FailureAnalyzer,
    failure_to_dict,
    source_context_to_dict,
)
from bumpshield.analysis.jar_inspector import JarInspectionError, JarInspector
from bumpshield.analysis.type_candidates import TypeCandidateExtractor
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.execution.javap import JavapExecution, JavapExecutor
from bumpshield.execution.maven import MavenEvidenceExecution, MavenExecutor
from bumpshield.models import (
    ApiAnalysisStatus,
    ApiEvidence,
    ApiEvidenceAnalysisResult,
    ApiEvidenceKind,
    ApiMatchStrategy,
    ApiMember,
    ApiMemberKind,
    ClassOwnershipStatus,
    DependencyAnalysisResult,
    DependencyAttribution,
    DependencyChange,
    DependencyChangeKind,
    DependencyCoordinate,
    DependencyKey,
    DependencyNode,
    EvidenceBundle,
    ExecutionResult,
    ExecutionStatus,
    FailureAnalysisResult,
    FailureCategory,
    FailureSignal,
    ResolvedArtifact,
    SourceContext,
    TaskSpec,
    TypeCandidate,
    WorkspaceKind,
)
from bumpshield.repo.workspace import RepositoryWorkspace, WorkspaceError, WorkspaceManager
from bumpshield.run import (
    RunSetupError,
    execution_log_text,
    generate_run_id,
    require_external_path,
    validate_task_repository,
)
from bumpshield.task_io import task_spec_to_dict

LOGGER = logging.getLogger(__name__)
_SUPPORTED_FAILURES = {
    FailureCategory.MISSING_SYMBOL,
    FailureCategory.METHOD_ARGUMENT_MISMATCH,
    FailureCategory.PACKAGE_NOT_FOUND,
    FailureCategory.INCOMPATIBLE_TYPES,
}
_MODIFIERS = {
    "public", "protected", "private", "static", "final", "abstract",
    "synchronized", "native", "strictfp", "default", "transient", "volatile",
}


class ApiEvidenceAnalysisError(RuntimeError):
    """Raised when trustworthy Phase 4 evidence collection cannot continue."""


class JavapParser:
    """Parse public method, constructor, and field declarations from ``javap``."""

    def parse(self, text: str, class_name: str) -> tuple[ApiMember, ...]:
        members: list[ApiMember] = []
        simple_class = class_name.rsplit(".", 1)[-1]
        for raw_line in text.splitlines():
            declaration = " ".join(raw_line.strip().split())
            if not declaration.startswith("public ") or not declaration.endswith(";"):
                continue
            clean = declaration[:-1].split(" throws ", 1)[0]
            if "(" in clean and clean.endswith(")"):
                prefix, parameters_text = clean.rsplit("(", 1)
                parameters = tuple(
                    _normalize_type(part)
                    for part in _split_parameters(parameters_text[:-1])
                    if part.strip()
                )
                tokens = prefix.split()
                if not tokens:
                    continue
                name = tokens[-1].rsplit(".", 1)[-1]
                constructor = name == simple_class
                members.append(
                    ApiMember(
                        kind=(
                            ApiMemberKind.CONSTRUCTOR
                            if constructor
                            else ApiMemberKind.METHOD
                        ),
                        name=name,
                        declaration=declaration,
                        parameter_types=parameters,
                        return_type=(
                            None
                            if constructor or len(tokens) < 2
                            else _normalize_type(tokens[-2])
                        ),
                        is_static="static" in tokens,
                    )
                )
                continue
            tokens = [token for token in clean.split() if token not in _MODIFIERS]
            if len(tokens) >= 2:
                members.append(
                    ApiMember(
                        kind=ApiMemberKind.FIELD,
                        name=tokens[-1].split("=", 1)[0],
                        declaration=declaration,
                        return_type=_normalize_type(tokens[-2]),
                        is_static=" static " in f" {clean} ",
                    )
                )
        return tuple(members)


def compare_relevant_api(
    class_name: str,
    failure: FailureSignal,
    before: DependencyCoordinate | None,
    after: DependencyCoordinate | None,
    old_members: tuple[ApiMember, ...],
    new_members: tuple[ApiMember, ...],
) -> ApiEvidence:
    """Compare failure-relevant declarations while preserving overloads."""
    member_name, expected_parameters = _failure_member(failure)
    if not member_name:
        kind = ApiEvidenceKind.CLASS_PRESENT_BOTH
        strategy = ApiMatchStrategy.NOT_APPLICABLE
        old_relevant: tuple[ApiMember, ...] = ()
        new_relevant: tuple[ApiMember, ...] = ()
    else:
        old_named = tuple(
            member for member in old_members if member.name == member_name
        )
        new_named = tuple(
            member for member in new_members if member.name == member_name
        )
        if expected_parameters is not None:
            old_exact = tuple(
                member
                for member in old_named
                if _parameters_match(member.parameter_types, expected_parameters)
            )
            new_exact = tuple(
                member
                for member in new_named
                if _parameters_match(member.parameter_types, expected_parameters)
            )
            strategy = ApiMatchStrategy.EXACT_PARAMETERS
            old_relevant = old_exact or old_named
            new_relevant = new_exact or new_named
            if old_exact and new_exact:
                kind = (
                    ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED
                    if _member_sets_equal(old_exact, new_exact)
                    else ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE
                )
            elif old_exact and new_named:
                kind = ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE
            elif old_exact:
                kind = ApiEvidenceKind.REMOVED_MEMBER
            elif new_exact and not old_named:
                kind = ApiEvidenceKind.ADDED_MEMBER
            else:
                kind = _compare_named_sets(old_named, new_named)
        else:
            strategy = ApiMatchStrategy.NAME_ONLY
            old_relevant = old_named
            new_relevant = new_named
            kind = _compare_named_sets(old_named, new_named)
    return ApiEvidence(
        kind=kind,
        class_name=class_name,
        failure_symbol=failure.symbol,
        before=before,
        after=after,
        old_class_present=True,
        new_class_present=True,
        old_members=old_relevant,
        new_members=new_relevant,
        old_class_members=old_members,
        new_class_members=new_members,
        match_strategy=strategy,
    )


def reconstruct_dependency_path(
    nodes: tuple[DependencyNode, ...],
    key: DependencyKey,
    task: TaskSpec,
) -> tuple[tuple[DependencyCoordinate, ...], bool]:
    """Reconstruct bounded parent provenance and report real target inclusion."""
    indexed = {node.key: node for node in nodes}
    current = indexed.get(key)
    reverse_path: list[DependencyCoordinate] = []
    seen: set[DependencyKey] = set()
    for _ in range(len(nodes) + 1):
        if current is None or current.key in seen:
            break
        seen.add(current.key)
        reverse_path.append(current.coordinate)
        current = indexed.get(current.parent) if current.parent else None
    path = tuple(reversed(reverse_path))
    requested = task.target_dependency
    target_on_path = any(
        item.group_id == requested.group_id and item.artifact_id == requested.artifact_id
        for item in path
    )
    return path, target_on_path


class ApiEvidenceAnalyzer:
    """Compose Phase 2 and Phase 3 services into targeted API evidence."""

    def __init__(
        self,
        runner: CommandRunner | None = None,
        maven: MavenEvidenceExecution | None = None,
        javap: JavapExecution | None = None,
        config: BumpShieldConfig | None = None,
        artifact_parser: ArtifactListParser | None = None,
        candidate_extractor: TypeCandidateExtractor | None = None,
        jar_inspector: JarInspector | None = None,
        javap_parser: JavapParser | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.maven = (
            maven if maven is not None else MavenExecutor(runner=self.runner)
        )
        self.javap = (
            javap if javap is not None else JavapExecutor(runner=self.runner)
        )
        self.config = config if config is not None else BumpShieldConfig()
        self.artifact_parser = artifact_parser or ArtifactListParser()
        self.candidate_extractor = candidate_extractor or TypeCandidateExtractor()
        self.jar_inspector = jar_inspector or JarInspector()
        self.javap_parser = javap_parser or JavapParser()
        self.dependency_analyzer = DependencyAnalyzer(
            runner=self.runner,
            maven=self.maven,
            config=self.config,
        )
        self.failure_analyzer = FailureAnalyzer(
            runner=self.runner,
            maven=self.maven,
            config=self.config,
        )

    def analyze(
        self,
        task: TaskSpec,
        run_id: str | None = None,
    ) -> ApiEvidenceAnalysisResult:
        """Collect primary-failure API evidence in detached temporary worktrees."""
        try:
            repository, repository_root = validate_task_repository(task, self.runner)
            effective_run_id = run_id or generate_run_id()
            artifact_path = self.config.run_directory(effective_run_id).resolve()
            require_external_path(artifact_path, repository_root)
            artifacts = ApiEvidenceArtifacts.create(artifact_path)
            artifacts.write_json("task.json", task_spec_to_dict(task))
        except RunSetupError as error:
            raise ApiEvidenceAnalysisError(str(error)) from error

        issues: list[str] = []
        try:
            with WorkspaceManager(repository, effective_run_id) as workspaces:
                base_workspace = workspaces.create(
                    task.base_commit, WorkspaceKind.BASE
                )
                base_tree = self.dependency_analyzer.collect_workspace(
                    base_workspace,
                    artifacts.path / "base-dependency-tree.txt",
                )
                base_artifacts = self._collect_artifacts(
                    base_workspace,
                    artifacts.path / "base-artifact-list.txt",
                )
                updated_workspace = workspaces.create(
                    task.updated_commit, WorkspaceKind.UPDATED
                )
                updated_tree = self.dependency_analyzer.collect_workspace(
                    updated_workspace,
                    artifacts.path / "updated-dependency-tree.txt",
                )
                updated_artifacts = self._collect_artifacts(
                    updated_workspace,
                    artifacts.path / "updated-artifact-list.txt",
                )
                dependency_diff = compare_dependency_trees(
                    base_tree.nodes, updated_tree.nodes, task
                )
                execution, failures, contexts, failure_status = (
                    self.failure_analyzer.analyze_workspace(updated_workspace)
                )
                if execution.status in {ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT}:
                    raise ApiEvidenceAnalysisError(
                        "updated Maven test execution ended with "
                        f"{execution.status.value}: "
                        f"{execution.detail or 'execution did not complete'}"
                    )
                failure_analysis = FailureAnalysisResult(
                    run_id=effective_run_id,
                    task=task,
                    artifact_directory=artifacts.path,
                    status=failure_status,
                    execution=execution,
                    failures=failures,
                    source_contexts=contexts,
                )
                primary = failure_analysis.primary_failure
                context = _primary_context(primary, contexts)
                candidates = (
                    self.candidate_extractor.extract(
                        primary, context, updated_workspace.path
                    )
                    if primary
                    else ()
                )
                attributions = self._attribute(
                    candidates,
                    primary,
                    dependency_diff.changes,
                    base_tree.nodes,
                    updated_tree.nodes,
                    base_artifacts,
                    updated_artifacts,
                    task,
                    artifacts,
                    issues,
                )
        except (
            WorkspaceError,
            DependencyAnalysisError,
            ArtifactListParseError,
        ) as error:
            raise ApiEvidenceAnalysisError(str(error)) from error

        dependency_analysis = DependencyAnalysisResult(
            run_id=effective_run_id,
            task=task,
            artifact_directory=artifacts.path,
            base=base_tree,
            updated=updated_tree,
            diff=dependency_diff,
        )
        api_evidence = tuple(
            item
            for attribution in attributions
            for item in attribution.api_evidence
        )
        bundle = EvidenceBundle(
            target_upgrade=task.target_dependency,
            run_id=effective_run_id,
            task=task,
            artifact_directory=artifacts.path,
            updated_execution=failure_analysis.execution,
            dependency_diff=dependency_analysis.diff,
            failures=(primary,) if primary else (),
            source_contexts=failure_analysis.source_contexts,
            dependency_attributions=attributions,
            api_evidence=api_evidence,
            issues=tuple(issues),
        )
        result = ApiEvidenceAnalysisResult(
            run_id=effective_run_id,
            task=task,
            artifact_directory=artifacts.path,
            status=_classify_analysis(primary, attributions, issues),
            dependency_analysis=dependency_analysis,
            failure_analysis=failure_analysis,
            candidates=candidates,
            base_artifacts=base_artifacts,
            updated_artifacts=updated_artifacts,
            attributions=attributions,
            issues=tuple(issues),
            evidence_bundle=bundle,
        )
        artifacts.persist(result)
        return result

    def _collect_artifacts(
        self,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> tuple[ResolvedArtifact, ...]:
        collection = self.maven.artifact_list(workspace, output_file)
        if collection.execution.status is not ExecutionStatus.PASS:
            raise ApiEvidenceAnalysisError(
                collection.execution.detail
                or "Maven artifact collection ended with "
                f"{collection.execution.status.value}"
            )
        return self.artifact_parser.parse(collection.raw_output)

    def _attribute(
        self,
        candidates: tuple[TypeCandidate, ...],
        failure: FailureSignal | None,
        changes: tuple[DependencyChange, ...],
        base_nodes: tuple[DependencyNode, ...],
        updated_nodes: tuple[DependencyNode, ...],
        base_artifacts: tuple[ResolvedArtifact, ...],
        updated_artifacts: tuple[ResolvedArtifact, ...],
        task: TaskSpec,
        artifacts: "ApiEvidenceArtifacts",
        issues: list[str],
    ) -> tuple[DependencyAttribution, ...]:
        relevant = tuple(
            change
            for change in changes
            if change.kind is not DependencyChangeKind.UNCHANGED
        )
        output: list[DependencyAttribution] = []
        for candidate in candidates:
            if candidate.project_owned:
                output.append(
                    DependencyAttribution(
                        candidate,
                        ClassOwnershipStatus.PROJECT_OWNED,
                    )
                )
                continue
            matches: list[tuple[DependencyChange, bool | None, bool | None]] = []
            for change in relevant:
                old_artifact = _resolve_artifact(base_artifacts, change.before, issues)
                new_artifact = _resolve_artifact(updated_artifacts, change.after, issues)
                old_present = (
                    False
                    if change.before is None
                    else self._owns(old_artifact, candidate, issues)
                )
                new_present = (
                    False
                    if change.after is None
                    else self._owns(new_artifact, candidate, issues)
                )
                if old_present is True or new_present is True:
                    matches.append((change, old_present, new_present))
            if not matches:
                output.append(
                    DependencyAttribution(candidate, ClassOwnershipStatus.NO_MATCH)
                )
                continue
            if len(matches) > 1:
                output.append(
                    DependencyAttribution(
                        candidate,
                        ClassOwnershipStatus.MULTIPLE_MATCHES,
                        dependencies=tuple(match[0] for match in matches),
                    )
                )
                continue
            change, old_present, new_present = matches[0]
            graph = (
                base_nodes
                if change.kind is DependencyChangeKind.REMOVED
                else updated_nodes
            )
            coordinate = (
                change.before
                if change.kind is DependencyChangeKind.REMOVED
                else change.after
            )
            assert coordinate is not None
            path, target_on_path = reconstruct_dependency_path(
                graph, coordinate.key, task
            )
            evidence = self._api_evidence(
                candidate,
                failure,
                change,
                old_present,
                new_present,
                _resolve_artifact(base_artifacts, change.before, issues),
                _resolve_artifact(updated_artifacts, change.after, issues),
                artifacts,
                issues,
            )
            output.append(
                DependencyAttribution(
                    candidate,
                    ClassOwnershipStatus.EXACT_SINGLE_MATCH,
                    dependencies=(change,),
                    dependency_path=path,
                    target_on_path=target_on_path,
                    api_evidence=(evidence,),
                )
            )
        return tuple(output)

    def _owns(
        self,
        artifact: ResolvedArtifact | None,
        candidate: TypeCandidate,
        issues: list[str],
    ) -> bool | None:
        if artifact is None:
            return None
        if artifact.coordinate.type not in {"jar", "test-jar", "bundle"}:
            _add_issue(
                issues,
                f"unsupported artifact type {artifact.coordinate.type}: "
                f"{artifact.path}",
            )
            return None
        try:
            if candidate.is_package:
                return self.jar_inspector.package_present(
                    artifact.path, candidate.name
                )
            return self.jar_inspector.class_present(artifact.path, candidate.name)
        except JarInspectionError as error:
            _add_issue(issues, str(error))
            return None

    def _api_evidence(
        self,
        candidate: TypeCandidate,
        failure: FailureSignal | None,
        change: DependencyChange,
        old_present: bool | None,
        new_present: bool | None,
        old_artifact: ResolvedArtifact | None,
        new_artifact: ResolvedArtifact | None,
        artifacts: "ApiEvidenceArtifacts",
        issues: list[str],
    ) -> ApiEvidence:
        if old_present is None or new_present is None:
            return _presence_evidence(
                ApiEvidenceKind.API_INSPECTION_UNAVAILABLE,
                candidate,
                failure,
                change,
                old_present,
                new_present,
            )
        if candidate.is_package:
            kind = (
                ApiEvidenceKind.PACKAGE_REMOVED
                if old_present and not new_present
                else ApiEvidenceKind.NO_RELEVANT_API_CHANGE
            )
            return _presence_evidence(
                kind, candidate, failure, change, old_present, new_present
            )
        if old_present and not new_present:
            kind = (
                ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS
                if change.kind is DependencyChangeKind.REMOVED
                else ApiEvidenceKind.REMOVED_CLASS
            )
            return _presence_evidence(kind, candidate, failure, change, True, False)
        if new_present and not old_present:
            return _presence_evidence(
                ApiEvidenceKind.ADDED_CLASS,
                candidate,
                failure,
                change,
                False,
                True,
            )
        if not old_artifact or not new_artifact or failure is None:
            return _presence_evidence(
                ApiEvidenceKind.NO_RELEVANT_API_CHANGE,
                candidate,
                failure,
                change,
                old_present,
                new_present,
            )
        old_result = self.javap.inspect(old_artifact.path, candidate.name)
        new_result = self.javap.inspect(new_artifact.path, candidate.name)
        artifacts.write_javap(
            "old", old_artifact.coordinate, candidate.name, old_result.execution
        )
        artifacts.write_javap(
            "new", new_artifact.coordinate, candidate.name, new_result.execution
        )
        if (
            old_result.execution.status is not ExecutionStatus.PASS
            or new_result.execution.status is not ExecutionStatus.PASS
        ):
            _add_issue(issues, "javap could not inspect both class versions")
            return _presence_evidence(
                ApiEvidenceKind.API_INSPECTION_UNAVAILABLE,
                candidate,
                failure,
                change,
                True,
                True,
            )
        return compare_relevant_api(
            candidate.name,
            failure,
            change.before,
            change.after,
            self.javap_parser.parse(old_result.raw_output, candidate.name),
            self.javap_parser.parse(new_result.raw_output, candidate.name),
        )


class ApiEvidenceArtifacts:
    """Single owner for Phase 4 artifact names and path-safe raw API files."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.api_path = path / "api"

    @classmethod
    def create(cls, path: Path) -> "ApiEvidenceArtifacts":
        try:
            path.mkdir(parents=True, exist_ok=False)
            (path / "api").mkdir()
        except OSError as error:
            raise ApiEvidenceAnalysisError(
                f"could not create run directory {path}: {error}"
            ) from error
        return cls(path)

    def write_javap(
        self,
        side: str,
        coordinate: DependencyCoordinate,
        class_name: str,
        execution: ExecutionResult,
    ) -> Path:
        identity = ":".join(
            (
                side,
                coordinate.group_id,
                coordinate.artifact_id,
                coordinate.version,
                coordinate.classifier or "main",
                class_name,
            )
        )
        path = self.api_path / safe_api_artifact_name(identity)
        self._write_text(path, execution_log_text(execution))
        return path

    def persist(self, result: ApiEvidenceAnalysisResult) -> None:
        dependency = result.dependency_analysis
        failure = result.failure_analysis
        self.write_json(
            "dependencies-before.json",
            {
                "commit": dependency.base.commit,
                "dependencies": [
                    dependency_node_to_dict(node) for node in dependency.base.nodes
                ],
            },
        )
        self.write_json(
            "dependencies-after.json",
            {
                "commit": dependency.updated.commit,
                "dependencies": [
                    dependency_node_to_dict(node)
                    for node in dependency.updated.nodes
                ],
            },
        )
        self.write_json(
            "dependency-diff.json",
            dependency_diff_to_dict(result.run_id, dependency.diff),
        )
        self._write_text(
            self.path / "updated-build.log",
            execution_log_text(failure.execution),
        )
        self.write_json(
            "failures.json",
            [failure_to_dict(item) for item in failure.failures],
        )
        self.write_json(
            "source-contexts.json",
            [source_context_to_dict(item) for item in failure.source_contexts],
        )
        self.write_json(
            "resolved-artifacts-before.json",
            [_artifact_to_dict(item) for item in result.base_artifacts],
        )
        self.write_json(
            "resolved-artifacts-after.json",
            [_artifact_to_dict(item) for item in result.updated_artifacts],
        )
        self.write_json(
            "class-attribution.json",
            [
                _attribution_to_dict(item, include_api=False)
                for item in result.attributions
            ],
        )
        api_evidence = tuple(
            item
            for attribution in result.attributions
            for item in attribution.api_evidence
        )
        self.write_json(
            "api-evidence.json",
            [_api_evidence_to_dict(item) for item in api_evidence],
        )
        bundle = result.evidence_bundle
        if bundle is None:  # pragma: no cover - guards malformed external results
            raise ApiEvidenceAnalysisError("Phase 4 result is missing its evidence bundle")
        self.write_json("evidence-bundle.json", _bundle_to_dict(result, bundle))

    def write_json(self, filename: str, data: object) -> None:
        self._write_text(self.path / filename, json.dumps(data, indent=2) + "\n")

    @staticmethod
    def _write_text(path: Path, text: str) -> None:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as error:
            raise ApiEvidenceAnalysisError(
                f"could not write artifact {path}: {error}"
            ) from error


def safe_api_artifact_name(identity: str) -> str:
    """Return readable, bounded filename immune to coordinate/class traversal."""
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "_", identity).strip("._-")
    return f"{(readable[:80] or 'api')}-{digest}.txt"


def _resolve_artifact(
    artifacts: tuple[ResolvedArtifact, ...],
    coordinate: DependencyCoordinate | None,
    issues: list[str],
) -> ResolvedArtifact | None:
    if coordinate is None:
        return None
    matches = [
        item
        for item in artifacts
        if item.coordinate.key == coordinate.key
        and item.coordinate.version == coordinate.version
    ]
    if len(matches) == 1:
        return matches[0]
    identity = f"{coordinate.group_id}:{coordinate.artifact_id}:{coordinate.version}"
    issue = (
        f"no resolved artifact path for {identity}"
        if not matches
        else f"multiple resolved artifact paths for {identity}"
    )
    _add_issue(issues, issue)
    return None


def _add_issue(issues: list[str], issue: str) -> None:
    if issue not in issues:
        issues.append(issue)


def _presence_evidence(
    kind: ApiEvidenceKind,
    candidate: TypeCandidate,
    failure: FailureSignal | None,
    change: DependencyChange,
    old_present: bool | None,
    new_present: bool | None,
) -> ApiEvidence:
    return ApiEvidence(
        kind=kind,
        class_name=candidate.name,
        failure_symbol=failure.symbol if failure else None,
        before=change.before,
        after=change.after,
        old_class_present=old_present,
        new_class_present=new_present,
    )


def _primary_context(
    failure: FailureSignal | None,
    contexts: tuple[SourceContext, ...],
) -> SourceContext | None:
    if failure is None:
        return None
    return next(
        (
            item
            for item in contexts
            if item.file == failure.file and item.focus_line == failure.line
        ),
        None,
    )


def _classify_analysis(
    failure: FailureSignal | None,
    attributions: tuple[DependencyAttribution, ...],
    issues: list[str],
) -> ApiAnalysisStatus:
    if failure is None or (
        failure.category not in _SUPPORTED_FAILURES and not failure.stack_frames
    ):
        return ApiAnalysisStatus.NO_SUPPORTED_FAILURE
    if any(
        item.ownership is ClassOwnershipStatus.MULTIPLE_MATCHES
        for item in attributions
    ):
        return ApiAnalysisStatus.AMBIGUOUS_ATTRIBUTION
    evidence = tuple(
        item for attribution in attributions for item in attribution.api_evidence
    )
    if any(
        item.kind is ApiEvidenceKind.API_INSPECTION_UNAVAILABLE
        for item in evidence
    ):
        return ApiAnalysisStatus.API_TOOL_UNAVAILABLE
    useful = {
        ApiEvidenceKind.REMOVED_CLASS,
        ApiEvidenceKind.ADDED_CLASS,
        ApiEvidenceKind.REMOVED_MEMBER,
        ApiEvidenceKind.ADDED_MEMBER,
        ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE,
        ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS,
        ApiEvidenceKind.PACKAGE_REMOVED,
    }
    if any(item.kind in useful for item in evidence):
        return (
            ApiAnalysisStatus.PARTIAL_EVIDENCE
            if issues
            else ApiAnalysisStatus.API_EVIDENCE_FOUND
        )
    if evidence:
        return ApiAnalysisStatus.CLASS_ATTRIBUTED_NO_API_CHANGE
    if issues:
        return ApiAnalysisStatus.PARTIAL_EVIDENCE
    return ApiAnalysisStatus.NO_CHANGED_DEPENDENCY_ATTRIBUTION


def _failure_member(
    failure: FailureSignal,
) -> tuple[str | None, tuple[str, ...] | None]:
    if not failure.symbol or failure.category is FailureCategory.PACKAGE_NOT_FOUND:
        return None, None
    cleaned = re.sub(r"^(?:method|class|variable)\s+", "", failure.symbol).strip()
    if "(" in cleaned and cleaned.endswith(")"):
        name, raw = cleaned.split("(", 1)
        return name.rsplit(".", 1)[-1], tuple(
            _normalize_type(part)
            for part in _split_parameters(raw[:-1])
            if part.strip()
        )
    parameters = None
    if failure.category is FailureCategory.METHOD_ARGUMENT_MISMATCH and failure.found:
        parameters = tuple(
            _normalize_type(part)
            for part in _split_parameters(failure.found)
            if part.strip()
        )
    return cleaned.rsplit(".", 1)[-1], parameters


def _compare_named_sets(
    old_members: tuple[ApiMember, ...],
    new_members: tuple[ApiMember, ...],
) -> ApiEvidenceKind:
    if old_members and new_members:
        return (
            ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED
            if _member_sets_equal(old_members, new_members)
            else ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE
        )
    if old_members:
        return ApiEvidenceKind.REMOVED_MEMBER
    if new_members:
        return ApiEvidenceKind.ADDED_MEMBER
    return ApiEvidenceKind.NO_RELEVANT_API_CHANGE


def _member_sets_equal(
    old_members: tuple[ApiMember, ...],
    new_members: tuple[ApiMember, ...],
) -> bool:
    return {_member_key(item) for item in old_members} == {
        _member_key(item) for item in new_members
    }


def _member_key(member: ApiMember) -> tuple[object, ...]:
    return (
        member.kind,
        member.name,
        tuple(_simple_type(item) for item in member.parameter_types),
        _simple_type(member.return_type) if member.return_type else None,
        member.is_static,
    )


def _parameters_match(actual: tuple[str, ...], expected: tuple[str, ...]) -> bool:
    return len(actual) == len(expected) and all(
        _simple_type(left) == _simple_type(right)
        for left, right in zip(actual, expected, strict=True)
    )


def _simple_type(value: str) -> str:
    suffix = "[]" if value.endswith("[]") else ""
    raw = value[:-2] if suffix else value
    return raw.rsplit(".", 1)[-1] + suffix


def _normalize_type(value: str) -> str:
    return re.sub(
        r"<.*>",
        "",
        " ".join(value.strip().split()).replace("...", "[]"),
    )


def _split_parameters(text: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(text):
        if character in "<([":
            depth += 1
        elif character in ">)]" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    if text[start:].strip():
        parts.append(text[start:].strip())
    return tuple(parts)


def _coordinate_to_dict(coordinate: DependencyCoordinate | None) -> object:
    if coordinate is None:
        return None
    return {
        "group_id": coordinate.group_id,
        "artifact_id": coordinate.artifact_id,
        "type": coordinate.type,
        "classifier": coordinate.classifier,
        "version": coordinate.version,
    }


def _artifact_to_dict(artifact: ResolvedArtifact) -> dict[str, object]:
    return {
        "coordinate": _coordinate_to_dict(artifact.coordinate),
        "scope": artifact.scope,
        "path": str(artifact.path),
        "exists": artifact.path.is_file(),
        "jar_compatible": artifact.coordinate.type in {"jar", "test-jar", "bundle"},
    }


def _member_to_dict(member: ApiMember) -> dict[str, object]:
    return {
        "kind": member.kind.value,
        "name": member.name,
        "declaration": member.declaration,
        "parameter_types": list(member.parameter_types),
        "return_type": member.return_type,
        "static": member.is_static,
    }


def _api_evidence_to_dict(evidence: ApiEvidence) -> dict[str, object]:
    return {
        "kind": evidence.kind.value,
        "class": evidence.class_name,
        "failure_symbol": evidence.failure_symbol,
        "before": _coordinate_to_dict(evidence.before),
        "after": _coordinate_to_dict(evidence.after),
        "old_class_present": evidence.old_class_present,
        "new_class_present": evidence.new_class_present,
        "old_members": [_member_to_dict(item) for item in evidence.old_members],
        "new_members": [_member_to_dict(item) for item in evidence.new_members],
        "old_class_members": [
            _member_to_dict(item) for item in evidence.old_class_members
        ],
        "new_class_members": [
            _member_to_dict(item) for item in evidence.new_class_members
        ],
        "match_strategy": evidence.match_strategy.value,
    }


def _attribution_to_dict(
    attribution: DependencyAttribution,
    *,
    include_api: bool = True,
) -> dict[str, object]:
    return {
        "candidate": {
            "name": attribution.candidate.name,
            "origin": attribution.candidate.origin.value,
            "project_owned": attribution.candidate.project_owned,
            "is_package": attribution.candidate.is_package,
        },
        "ownership": attribution.ownership.value,
        "dependencies": [
            {
                "kind": item.kind.value,
                "relationship": item.relationship.value,
                "is_target": item.is_target,
                "before": _coordinate_to_dict(item.before),
                "after": _coordinate_to_dict(item.after),
            }
            for item in attribution.dependencies
        ],
        "dependency_path": [
            _coordinate_to_dict(item) for item in attribution.dependency_path
        ],
        "target_on_path": attribution.target_on_path,
        "api_evidence": (
            [
                _api_evidence_to_dict(item)
                for item in attribution.api_evidence
            ]
            if include_api
            else None
        ),
    }


def _bundle_to_dict(
    result: ApiEvidenceAnalysisResult,
    bundle: EvidenceBundle,
) -> dict[str, object]:
    primary = result.failure_analysis.primary_failure
    return {
        "run_id": result.run_id,
        "status": result.status.value,
        "target_upgrade": task_spec_to_dict(result.task)["target_dependency"],
        "changed_dependencies": [
            {
                "kind": item.kind.value,
                "relationship": item.relationship.value,
                "is_target": item.is_target,
                "before": _coordinate_to_dict(item.before),
                "after": _coordinate_to_dict(item.after),
            }
            for item in bundle.dependency_diff.changes
            if item.kind is not DependencyChangeKind.UNCHANGED
        ],
        "primary_failure": failure_to_dict(primary) if primary else None,
        "source_contexts": [
            source_context_to_dict(item) for item in bundle.source_contexts
        ],
        "dependency_attributions": [
            _attribution_to_dict(item)
            for item in bundle.dependency_attributions
        ],
        "api_evidence": [
            _api_evidence_to_dict(item) for item in bundle.api_evidence
        ],
        "issues": list(result.issues),
    }
