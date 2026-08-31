"""Independent dependency, execution, test-integrity, and patch verification."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from bumpshield.analysis.dependency_diff import (
    DependencyTreeParseError,
    DependencyTreeParser,
)
from bumpshield.execution.maven import MavenDependencyExecution
from bumpshield.models import (
    DependencyCoordinate,
    DependencyNode,
    DependencyValidationResult,
    ExecutionResult,
    ExecutionStatus,
    MigrationPlan,
    PatchAnalysis,
    PatchScopeStatus,
    TaskSpec,
    VerificationCheck,
    VerificationCheckStatus,
    VerificationResult,
    VerificationStatus,
)
from bumpshield.repo.workspace import RepositoryWorkspace


class RepairMavenExecution(MavenDependencyExecution, Protocol):
    """Maven commands independently required after a provider patch."""

    def execute_lifecycle(
        self,
        workspace: RepositoryWorkspace,
        goal: str,
    ) -> ExecutionResult:
        """Run compile or test independently."""
        ...


class DependencyValidator:
    """Resolve patched Maven graph and enforce target/causal versions."""

    def __init__(
        self,
        maven: MavenDependencyExecution,
        parser: DependencyTreeParser | None = None,
    ) -> None:
        self.maven = maven
        self.parser = parser or DependencyTreeParser()

    def validate(
        self,
        task: TaskSpec,
        plan: MigrationPlan,
        workspace: RepositoryWorkspace,
        output_file: Path,
    ) -> DependencyValidationResult:
        """Return observed versions; never infer success from manifest text."""
        collection = self.maven.dependency_tree(workspace, output_file)
        if collection.execution.status is not ExecutionStatus.PASS:
            detail = collection.execution.detail or (
                "patched Maven dependency resolution did not pass"
            )
            return DependencyValidationResult(
                execution=collection.execution,
                target_retained=False,
                causal_dependency_retained=False,
                resolved_target_version=None,
                resolved_causal_version=None,
                issues=(detail,),
            )
        try:
            parsed = self.parser.parse(collection.raw_output)
        except DependencyTreeParseError as error:
            return DependencyValidationResult(
                execution=collection.execution,
                target_retained=False,
                causal_dependency_retained=False,
                resolved_target_version=None,
                resolved_causal_version=None,
                issues=(f"could not parse patched dependency resolution: {error}",),
            )

        target = _find_target(parsed.nodes, task)
        resolved_target = target.version if target else None
        target_retained = resolved_target == task.target_dependency.new_version
        causal_expected = (
            plan.affected_dependency.after
            if plan.affected_dependency is not None
            else None
        )
        causal = _find_coordinate(parsed.nodes, causal_expected)
        resolved_causal = causal.version if causal else None
        causal_retained = (
            True
            if causal_expected is None
            else resolved_causal == causal_expected.version
        )
        issues: list[str] = []
        if not target_retained:
            issues.append(
                "target dependency resolved "
                f"{resolved_target or 'NOT_FOUND'}, expected "
                f"{task.target_dependency.new_version}"
            )
        if not causal_retained and causal_expected is not None:
            issues.append(
                "causal dependency resolved "
                f"{resolved_causal or 'NOT_FOUND'}, expected "
                f"{causal_expected.version}"
            )
        return DependencyValidationResult(
            execution=collection.execution,
            target_retained=target_retained,
            causal_dependency_retained=causal_retained,
            resolved_target_version=resolved_target,
            resolved_causal_version=resolved_causal,
            issues=tuple(issues),
        )


class IndependentVerifier:
    """Compute final verification solely from Git and Maven observations."""

    def verify(
        self,
        dependency: DependencyValidationResult,
        compile_result: ExecutionResult,
        test_result: ExecutionResult,
        patch: PatchAnalysis,
    ) -> VerificationResult:
        """Return verified only when every mandatory objective check passes."""
        checks = (
            _boolean_check(
                "TARGET_DEPENDENCY",
                dependency.target_retained,
                "requested upgraded target version retained",
                "; ".join(dependency.issues) or "target version mismatch",
            ),
            _boolean_check(
                "CAUSAL_DEPENDENCY",
                dependency.causal_dependency_retained,
                "causal dependency resolution retained",
                "; ".join(dependency.issues) or "causal dependency mismatch",
            ),
            _execution_check("COMPILE", compile_result),
            _execution_check("TESTS", test_result),
            _boolean_check(
                "TEST_FILES",
                not patch.deleted_test_files,
                "no test files deleted",
                "deleted: " + ", ".join(map(str, patch.deleted_test_files)),
            ),
            _boolean_check(
                "TEST_DISABLEMENT",
                not patch.newly_disabled_test_files,
                "no new test disablement",
                "new disablement: "
                + ", ".join(map(str, patch.newly_disabled_test_files)),
            ),
            _boolean_check(
                "TEST_SKIPPING",
                not patch.test_skip_introduced,
                "no Maven test skipping introduced",
                "Maven test skipping introduced",
            ),
            _scope_check(patch),
            _patch_safety_check(patch),
        )
        if any(check.status is VerificationCheckStatus.FAIL for check in checks):
            status = VerificationStatus.VERIFICATION_FAILED
        elif any(check.status is VerificationCheckStatus.REVIEW for check in checks):
            status = VerificationStatus.NEEDS_HUMAN_REVIEW
        else:
            status = VerificationStatus.VERIFIED_MIGRATION
        reasons = tuple(
            check.details
            for check in checks
            if check.status is not VerificationCheckStatus.PASS
        )
        return VerificationResult(
            status=status,
            target_dependency_retained=dependency.target_retained,
            causal_dependency_retained=dependency.causal_dependency_retained,
            compilation_passed=compile_result.status is ExecutionStatus.PASS,
            tests_passed=test_result.status is ExecutionStatus.PASS,
            tests_preserved=not patch.deleted_test_files,
            tests_enabled=not patch.newly_disabled_test_files,
            test_execution_not_skipped=not patch.test_skip_introduced,
            patch_scope_acceptable=not patch.review_issues
            and patch.scope_status is not PatchScopeStatus.OUT_OF_SCOPE,
            checks=checks,
            reasons=reasons,
        )


def _find_target(
    nodes: tuple[DependencyNode, ...], task: TaskSpec
) -> DependencyCoordinate | None:
    matches = tuple(
        node.coordinate
        for node in nodes
        if node.coordinate.group_id == task.target_dependency.group_id
        and node.coordinate.artifact_id == task.target_dependency.artifact_id
    )
    return matches[0] if len(matches) == 1 else None


def _find_coordinate(
    nodes: tuple[DependencyNode, ...], expected: DependencyCoordinate | None
) -> DependencyCoordinate | None:
    if expected is None:
        return None
    matches = tuple(node.coordinate for node in nodes if node.key == expected.key)
    return matches[0] if len(matches) == 1 else None


def _boolean_check(
    name: str,
    passed: bool,
    success: str,
    failure: str,
) -> VerificationCheck:
    return VerificationCheck(
        name,
        VerificationCheckStatus.PASS if passed else VerificationCheckStatus.FAIL,
        success if passed else failure,
    )


def _execution_check(name: str, execution: ExecutionResult) -> VerificationCheck:
    return VerificationCheck(
        name,
        (
            VerificationCheckStatus.PASS
            if execution.status is ExecutionStatus.PASS
            else VerificationCheckStatus.FAIL
        ),
        f"Maven {name.lower()} status: {execution.status.value}",
    )


def _scope_check(patch: PatchAnalysis) -> VerificationCheck:
    if patch.scope_status is PatchScopeStatus.OUT_OF_SCOPE:
        return VerificationCheck(
            "PATCH_SCOPE",
            VerificationCheckStatus.REVIEW,
            "out-of-scope files: " + ", ".join(map(str, patch.out_of_scope_files)),
        )
    return VerificationCheck(
        "PATCH_SCOPE",
        VerificationCheckStatus.PASS,
        f"patch scope: {patch.scope_status.value}",
    )


def _patch_safety_check(patch: PatchAnalysis) -> VerificationCheck:
    if patch.fatal_issues:
        return VerificationCheck(
            "PATCH_SAFETY",
            VerificationCheckStatus.FAIL,
            "; ".join(patch.fatal_issues),
        )
    if patch.review_issues:
        return VerificationCheck(
            "PATCH_SAFETY",
            VerificationCheckStatus.REVIEW,
            "; ".join(patch.review_issues),
        )
    return VerificationCheck(
        "PATCH_SAFETY",
        VerificationCheckStatus.PASS,
        "no forbidden or suspicious deterministic patch findings",
    )
