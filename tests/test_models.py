from pathlib import Path

import pytest

from bumpshield.config import BumpShieldConfig, validate_run_id
from bumpshield.models import (
    DependencyChange,
    DependencyChangeKind,
    DependencyCoordinate,
    DependencyRelationship,
    DependencyUpgrade,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    FailureSignal,
    RepairAttempt,
    RootCauseHypothesis,
    SourceContext,
    SourceLine,
    TaskSpec,
    VerificationResult,
    VerificationStatus,
    WorkspaceKind,
)
from bumpshield.repo.workspace import RepositoryWorkspace


def test_task_spec_has_typed_dependency_upgrade() -> None:
    upgrade = DependencyUpgrade(
        group_id="org.example",
        artifact_id="foo",
        old_version="2.8.0",
        new_version="3.0.0",
    )

    task = TaskSpec(
        repository=Path("/repos/example"),
        base_commit="abc123",
        updated_commit="def456",
        target_dependency=upgrade,
    )

    assert task.repository == Path("/repos/example")
    assert task.target_dependency.new_version == "3.0.0"


@pytest.mark.parametrize("field", ["group_id", "artifact_id", "old_version", "new_version"])
def test_dependency_upgrade_rejects_empty_fields(field: str) -> None:
    values = {
        "group_id": "org.example",
        "artifact_id": "foo",
        "old_version": "2.8.0",
        "new_version": "3.0.0",
    }
    values[field] = " "

    with pytest.raises(ValueError, match=field):
        DependencyUpgrade(**values)


def test_hypothesis_evidence_score_is_bounded() -> None:
    from bumpshield.models import (
        CausalHypothesisKind,
        EvidenceStrength,
        HypothesisStatus,
    )

    with pytest.raises(ValueError, match="evidence score"):
        RootCauseHypothesis(
            id="H1",
            rank=1,
            status=HypothesisStatus.SUPPORTED,
            kind=CausalHypothesisKind.REMOVED_MEMBER,
            summary="API removed",
            implicated_dependencies=(),
            dependency_path=(),
            target_on_path=False,
            failure=None,
            causal_chain=(),
            supporting_evidence=(),
            contradictory_evidence=(),
            missing_evidence=(),
            evidence_strength=EvidenceStrength.VERY_STRONG,
            evidence_score=101,
            explanation="Evidence supports an API removal.",
        )


def test_dependency_change_requires_coordinates_matching_kind() -> None:
    coordinate = DependencyCoordinate("org.example", "foo", "3.0.0")

    with pytest.raises(ValueError, match="ADDED"):
        DependencyChange(
            kind=DependencyChangeKind.ADDED,
            relationship=DependencyRelationship.DIRECT,
            before=coordinate,
            after=coordinate,
        )


def test_repair_attempt_requires_positive_attempt_number() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        RepairAttempt(
            attempt_number=0,
            execution=ExecutionResult(status=ExecutionStatus.FAIL),
        )


def test_verification_uses_explicit_status() -> None:
    result = VerificationResult(
        status=VerificationStatus.VERIFIED_MIGRATION,
        target_dependency_retained=True,
        compilation_passed=True,
        tests_passed=True,
    )

    assert result.status is VerificationStatus.VERIFIED_MIGRATION


def test_workspace_records_role_path_and_commit(tmp_path: Path) -> None:
    workspace = RepositoryWorkspace(
        path=tmp_path,
        commit="abc123",
        kind=WorkspaceKind.BASE,
    )

    assert workspace.path == tmp_path
    assert workspace.kind is WorkspaceKind.BASE


def test_run_artifact_paths_are_conventional_without_creation(tmp_path: Path) -> None:
    config = BumpShieldConfig(state_root=tmp_path / "state")

    assert config.runs_directory == tmp_path / "state" / "runs"
    assert config.run_directory("run-123") == tmp_path / "state" / "runs" / "run-123"
    assert not config.state_root.exists()


@pytest.mark.parametrize("run_id", ["", "..", "nested/run"])
def test_run_id_must_be_one_safe_path_component(tmp_path: Path, run_id: str) -> None:
    config = BumpShieldConfig(state_root=tmp_path / "state")

    with pytest.raises(ValueError, match="run_id"):
        config.run_directory(run_id)


def test_run_id_validation_is_reusable_for_workspaces() -> None:
    assert validate_run_id("run-123") == "run-123"


def test_failure_signal_uses_one_based_positions() -> None:
    with pytest.raises(ValueError, match="line"):
        FailureSignal(
            category=FailureCategory.MISSING_SYMBOL,
            message="cannot find symbol",
            line=0,
        )


def test_source_context_requires_repository_relative_file() -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        SourceContext(
            file=Path("/tmp/Foo.java"),
            start_line=1,
            end_line=1,
            focus_line=1,
            lines=(SourceLine(1, "class Foo {}"),),
        )
