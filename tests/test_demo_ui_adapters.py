from __future__ import annotations

import json
from pathlib import Path

import pytest

from bumpshield.models import (
    ApiEvidence,
    ApiEvidenceKind,
    ApiMember,
    ApiMemberKind,
    CandidateMatchReason,
    CausalDiagnosis,
    CausalHypothesisKind,
    CausalStep,
    CausalStepKind,
    DependencyChange,
    DependencyChangeKind,
    DependencyCoordinate,
    DependencyRelationship,
    DependencyUpgrade,
    DiagnosisStatus,
    EvidenceStrength,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
    FailureSignal,
    HypothesisStatus,
    MigrationCandidate,
    MigrationCandidateKind,
    MigrationKind,
    MigrationPlan,
    MigrationStatus,
    PatchAnalysis,
    PatchScopeStatus,
    PatchStats,
    PlanScope,
    PlanStatus,
    RepairAttempt,
    RepairAttemptStatus,
    RepairConstraint,
    RepairResult,
    RootCauseHypothesis,
    SourceContext,
    SourceLine,
    TaskSpec,
    VerificationCheck,
    VerificationCheckStatus,
    VerificationResult,
    VerificationStatus,
)
from demo_ui.adapters import (
    TaskFormValues,
    api_to_view,
    build_task_spec,
    dependency_path_labels,
    diagnosis_to_view,
    failure_to_view,
    friendly_error,
    list_artifacts,
    load_demo_values,
    load_research_results,
    plan_to_view,
    read_artifact_text,
    repair_to_view,
    status_tone,
    task_preview,
)
from demo_ui.state import form_values, initialize_state, reset_run_state, set_form_values


def _coordinate(artifact: str, version: str) -> DependencyCoordinate:
    return DependencyCoordinate("com.example", artifact, version)


def _change() -> DependencyChange:
    return DependencyChange(
        kind=DependencyChangeKind.UPDATED,
        relationship=DependencyRelationship.TRANSITIVE,
        before=_coordinate("parser", "1.0"),
        after=_coordinate("parser", "2.0"),
    )


def _failure() -> FailureSignal:
    return FailureSignal(
        category=FailureCategory.MISSING_SYMBOL,
        message="cannot find symbol",
        file=Path("src/main/java/example/Foo.java"),
        line=9,
        symbol="parseValue(java.lang.String)",
    )


def _diagnosis() -> CausalDiagnosis:
    hypothesis = RootCauseHypothesis(
        id="hypothesis-1",
        rank=1,
        status=HypothesisStatus.SUPPORTED,
        kind=CausalHypothesisKind.REMOVED_MEMBER,
        summary="parser 2.0 removed parseValue",
        implicated_dependencies=(_change(),),
        dependency_path=(_coordinate("core", "2.0"), _coordinate("parser", "2.0")),
        target_on_path=True,
        failure=_failure(),
        causal_chain=(
            CausalStep(1, CausalStepKind.TARGET_UPGRADE, "core changed", ("e1",)),
            CausalStep(2, CausalStepKind.API_CHANGE, "parseValue removed", ("e2",)),
        ),
        supporting_evidence=(),
        contradictory_evidence=(),
        missing_evidence=(),
        evidence_strength=EvidenceStrength.VERY_STRONG,
        evidence_score=100,
        explanation="Old API exists; new API does not.",
    )
    return CausalDiagnosis(
        run_id="run-1",
        status=DiagnosisStatus.SUPPORTED_DIAGNOSIS,
        artifact_directory=Path("/tmp/run-1"),
        hypotheses=(hypothesis,),
        summary="Supported causal diagnosis",
    )


def _member(name: str, declaration: str) -> ApiMember:
    return ApiMember(ApiMemberKind.METHOD, name, declaration)


def _candidate() -> MigrationCandidate:
    return MigrationCandidate(
        rank=1,
        class_name="com.example.Parser",
        member=_member("parse", "public String parse(String, Options)"),
        kind=MigrationCandidateKind.RELATED_SAME_CLASS_MEMBER,
        match_reasons=(CandidateMatchReason.SAME_DECLARING_CLASS,),
        evidence_strength=EvidenceStrength.STRONG,
    )


def _plan() -> MigrationPlan:
    return MigrationPlan(
        plan_id="plan-1",
        run_id="run-1",
        artifact_directory=Path("/tmp/run-1"),
        status=PlanStatus.PLAN_READY,
        diagnosis_status=DiagnosisStatus.SUPPORTED_DIAGNOSIS,
        hypothesis_id="hypothesis-1",
        migration_kind=MigrationKind.REMOVED_METHOD,
        summary="Migrate removed method",
        target_upgrade=DependencyUpgrade("com.example", "core", "1.0", "2.0"),
        affected_dependency=_change(),
        affected_class="com.example.Parser",
        affected_member="parseValue(java.lang.String)",
        old_api=(_member("parseValue", "public String parseValue(String)"),),
        new_api_candidates=(_candidate(),),
        missing_parameter_types=(),
        primary_source_location=None,
        affected_source_locations=(),
        allowed_files=(Path("src/main/java/example/Foo.java"),),
        protected_files=(Path("pom.xml"),),
        required_outcome="Stop using parseValue while retaining parser 2.0",
        constraints=(RepairConstraint.TARGET_VERSION_MUST_REMAIN, RepairConstraint.NO_TEST_DELETION),
        verification_requirements=(),
        verification_commands=(),
        scope=PlanScope.SMALL,
        cautious_repair=False,
        additional_file_policy="Additional files require evidence.",
    )


def test_task_form_builds_existing_task_spec_and_preview(tmp_path: Path) -> None:
    values = TaskFormValues(
        repository=str(tmp_path),
        base_commit="base",
        updated_commit="updated",
        group_id="com.example",
        artifact_id="core",
        old_version="1.0",
        new_version="2.0",
    )

    task = build_task_spec(values)

    assert isinstance(task, TaskSpec)
    assert task.repository == tmp_path.resolve()
    assert json.loads(task_preview(task))["target_dependency"]["new_version"] == "2.0"


def test_task_form_rejects_missing_fields() -> None:
    with pytest.raises(ValueError, match="Missing required fields"):
        build_task_spec(TaskFormValues())


def test_demo_shortcut_reads_manifest_without_executing() -> None:
    values = load_demo_values()

    assert values.artifact_id == "core-lib"
    assert values.new_version == "2.0.0"
    assert values.repository.endswith("benchmark/runtime/transitive-removed-method/application")


def test_dependency_path_formatting_is_deterministic() -> None:
    assert dependency_path_labels((_coordinate("core", "2.0"), _coordinate("parser", "2.0"))) == (
        "com.example:core:2.0",
        "com.example:parser:2.0",
    )


def test_failure_view_uses_matching_bounded_source_context() -> None:
    context = SourceContext(
        file=Path("src/main/java/example/Foo.java"),
        start_line=8,
        end_line=10,
        focus_line=9,
        lines=(SourceLine(8, "before"), SourceLine(9, "parser.parseValue(x);"), SourceLine(10, "after")),
    )

    view = failure_to_view(_failure(), (context,))

    assert view is not None
    assert view.category == "MISSING_SYMBOL"
    assert ">    9 | parser.parseValue(x);" in (view.source_excerpt or "")


def test_api_view_keeps_candidate_unverified() -> None:
    evidence = ApiEvidence(
        kind=ApiEvidenceKind.REMOVED_MEMBER,
        class_name="com.example.Parser",
        failure_symbol="parseValue",
        before=_coordinate("parser", "1.0"),
        after=_coordinate("parser", "2.0"),
        old_class_present=True,
        new_class_present=True,
        old_members=(_member("parseValue", "public String parseValue(String)"),),
    )

    view = api_to_view(evidence, (_candidate(),))

    assert view is not None
    assert view.kind == "REMOVED_MEMBER"
    assert view.candidates == ("public String parse(String, Options)",)
    assert _candidate().verified_replacement is False


def test_diagnosis_view_preserves_ordinal_evidence() -> None:
    view = diagnosis_to_view(_diagnosis())

    assert view.status == "SUPPORTED_DIAGNOSIS"
    assert view.evidence_strength == "VERY_STRONG"
    assert view.evidence_score == 100
    assert view.causal_steps == ("core changed", "parseValue removed")


def test_plan_view_exposes_boundary_and_guardrails() -> None:
    view = plan_to_view(_plan())

    assert view.status == "PLAN_READY"
    assert view.allowed_files == ("src/main/java/example/Foo.java",)
    assert "NO_TEST_DELETION" in view.constraints
    assert view.candidates == ("public String parse(String, Options)",)


def test_verified_ui_requires_engine_and_verifier_success(tmp_path: Path) -> None:
    verification = VerificationResult(
        status=VerificationStatus.VERIFIED_MIGRATION,
        target_dependency_retained=True,
        compilation_passed=True,
        tests_passed=True,
        checks=(VerificationCheck("tests", VerificationCheckStatus.PASS, "Tests pass"),),
    )
    result = RepairResult(
        run_id="run-1",
        status=MigrationStatus.UNRESOLVED,
        artifact_directory=tmp_path,
        attempts=(),
        winning_attempt=None,
        verification=verification,
        total_duration_seconds=1.0,
    )

    assert repair_to_view(result).verified is False


def test_attempt_view_uses_git_patch_stats(tmp_path: Path) -> None:
    verification = VerificationResult(
        status=VerificationStatus.VERIFIED_MIGRATION,
        target_dependency_retained=True,
        compilation_passed=True,
        tests_passed=True,
    )
    patch = PatchAnalysis(
        patch="-old\n+new\n",
        changed_files=(Path("src/main/java/example/Foo.java"),),
        added_files=(),
        deleted_files=(),
        out_of_scope_files=(),
        evidence_backed_expansions=(),
        deleted_test_files=(),
        newly_disabled_test_files=(),
        test_skip_introduced=False,
        manifest_files_changed=(),
        scope_status=PatchScopeStatus.IN_SCOPE,
        stats=PatchStats(files_changed=1, lines_added=1, lines_removed=1),
    )
    attempt = RepairAttempt(
        attempt_number=1,
        execution=ExecutionResult(ExecutionStatus.PASS),
        status=RepairAttemptStatus.VERIFIED,
        patch_analysis=patch,
        compile_result=ExecutionResult(ExecutionStatus.PASS),
        test_result=ExecutionResult(ExecutionStatus.PASS),
        verification=verification,
    )
    result = RepairResult(
        run_id="run-1",
        status=MigrationStatus.VERIFIED_MIGRATION,
        artifact_directory=tmp_path,
        attempts=(attempt,),
        winning_attempt=1,
        verification=verification,
        total_duration_seconds=1.0,
    )

    view = repair_to_view(result)

    assert view.verified is True
    assert view.attempts[0].files_changed == 1
    assert view.attempts[0].patch == "-old\n+new\n"


def test_research_metrics_are_loaded_from_frozen_snapshot() -> None:
    view = load_research_results()

    assert view.total_cases == 20
    assert (view.direct_cases, view.transitive_cases) == (10, 10)
    assert [(item.strategy, item.verified) for item in view.strategies] == [
        ("direct-one-shot", 20),
        ("direct-retry", 20),
        ("bumpshield", 18),
    ]
    assert (view.dependency_correct, view.api_correct) == (20, 12)
    assert (view.transitive_dependency_correct, view.transitive_dependency_labeled) == (10, 10)


def test_artifact_reader_rejects_escape_and_bounds_output(tmp_path: Path) -> None:
    (tmp_path / "report.txt").write_text("x" * 20, encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    assert list_artifacts(tmp_path) == (Path("report.txt"),)
    assert "artifact truncated" in read_artifact_text(tmp_path, Path("report.txt"), max_bytes=5)
    with pytest.raises(ValueError, match="escapes"):
        read_artifact_text(tmp_path, Path("../outside.txt"))


def test_status_and_quota_error_mapping_are_explicit() -> None:
    assert status_tone("VERIFIED_MIGRATION") == "success"
    assert status_tone("NEEDS_HUMAN_REVIEW") == "review"
    assert status_tone("COMPILE_FAILED") == "failure"
    assert friendly_error("Codex quota exhausted")[0] == "CODING PROVIDER UNAVAILABLE"


def test_session_state_prevents_implicit_result_loss() -> None:
    state = {}
    initialize_state(state)
    values = TaskFormValues(repository="/repo", base_commit="a", updated_commit="b")
    set_form_values(state, values)
    state["planning_result"] = object()

    initialize_state(state)

    assert form_values(state).repository == "/repo"
    assert state["planning_result"] is not None
    reset_run_state(state)
    assert state["planning_result"] is None
