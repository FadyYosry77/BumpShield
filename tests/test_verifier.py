from pathlib import Path

from bumpshield.execution.verifier import IndependentVerifier
from bumpshield.models import (
    DependencyValidationResult,
    ExecutionResult,
    ExecutionStatus,
    PatchAnalysis,
    PatchScopeStatus,
    PatchStats,
    VerificationStatus,
)


def _execution(status: ExecutionStatus = ExecutionStatus.PASS) -> ExecutionResult:
    return ExecutionResult(status)


def _dependency(**changes) -> DependencyValidationResult:
    values = {
        "execution": _execution(),
        "target_retained": True,
        "causal_dependency_retained": True,
        "resolved_target_version": "2.0",
        "resolved_causal_version": "5.0",
    }
    values.update(changes)
    return DependencyValidationResult(**values)


def _patch(**changes) -> PatchAnalysis:
    values = {
        "patch": "diff --git a/Foo.java b/Foo.java\n",
        "changed_files": (Path("Foo.java"),),
        "added_files": (),
        "deleted_files": (),
        "out_of_scope_files": (),
        "evidence_backed_expansions": (),
        "deleted_test_files": (),
        "newly_disabled_test_files": (),
        "test_skip_introduced": False,
        "manifest_files_changed": (),
        "scope_status": PatchScopeStatus.IN_SCOPE,
        "stats": PatchStats(files_changed=1, lines_added=1, lines_removed=1),
    }
    values.update(changes)
    return PatchAnalysis(**values)


def test_verifier_requires_all_objective_checks() -> None:
    result = IndependentVerifier().verify(
        _dependency(), _execution(), _execution(), _patch()
    )

    assert result.status is VerificationStatus.VERIFIED_MIGRATION
    assert all(check.status.value == "PASS" for check in result.checks)


def test_green_build_with_dependency_downgrade_is_not_verified() -> None:
    result = IndependentVerifier().verify(
        _dependency(target_retained=False, issues=("target downgraded",)),
        _execution(),
        _execution(),
        _patch(),
    )

    assert result.status is VerificationStatus.VERIFICATION_FAILED
    assert not result.target_dependency_retained


def test_green_build_with_deleted_disabled_or_skipped_tests_is_not_verified() -> None:
    patch = _patch(
        deleted_test_files=(Path("src/test/java/FooTest.java"),),
        newly_disabled_test_files=(Path("src/test/java/BarTest.java"),),
        test_skip_introduced=True,
        fatal_issues=("test cheating",),
    )

    result = IndependentVerifier().verify(
        _dependency(), _execution(), _execution(), patch
    )

    assert result.status is VerificationStatus.VERIFICATION_FAILED
    assert not result.tests_preserved
    assert not result.tests_enabled
    assert not result.test_execution_not_skipped


def test_green_broad_or_out_of_scope_patch_requires_human_review() -> None:
    patch = _patch(
        out_of_scope_files=(Path("README.md"),),
        scope_status=PatchScopeStatus.OUT_OF_SCOPE,
        review_issues=("patch is broad",),
    )

    result = IndependentVerifier().verify(
        _dependency(), _execution(), _execution(), patch
    )

    assert result.status is VerificationStatus.NEEDS_HUMAN_REVIEW


def test_provider_claim_cannot_override_actual_test_failure() -> None:
    result = IndependentVerifier().verify(
        _dependency(), _execution(), _execution(ExecutionStatus.FAIL), _patch()
    )

    assert result.status is VerificationStatus.VERIFICATION_FAILED
    assert not result.tests_passed
