import json
from dataclasses import replace
from pathlib import Path

import pytest

from bumpshield.agent.investigator import DeterministicInvestigator
from bumpshield.agent.repairer import (
    BASE_REPAIR_CONSTRAINTS,
    BASE_VERIFICATION_REQUIREMENTS,
    MigrationPlanArtifacts,
    MigrationPlanner,
    RepairContextBuilder,
    estimate_scope,
    migration_plan_to_dict,
    rank_api_candidates,
)
from bumpshield.models import (
    AffectedLocationKind,
    AffectedSourceLocation,
    ApiEvidenceKind,
    DiagnosisStatus,
    EvidenceStrength,
    MigrationKind,
    PlanScope,
    PlanStatus,
    RepairConstraint,
    SourceFileKind,
    VerificationRequirement,
)
from test_investigator import make_bundle, member, removed_change, updated_change


def _planning_inputs(
    api_kind: ApiEvidenceKind = ApiEvidenceKind.REMOVED_MEMBER,
    *,
    new_class_members=(),
    change=None,
):
    bundle = make_bundle(
        api_kind,
        change=change or updated_change(old_version="4.0", new_version="5.0"),
    )
    api = replace(bundle.api_evidence[0], new_class_members=new_class_members)
    attribution = replace(
        bundle.dependency_attributions[0], api_evidence=(api,)
    )
    bundle = replace(
        bundle, api_evidence=(api,), dependency_attributions=(attribution,)
    )
    diagnosis = DeterministicInvestigator().investigate(bundle)
    return bundle, diagnosis


def _location(
    file: str = "src/main/java/com/example/Foo.java",
    line: int = 84,
    kind: AffectedLocationKind = AffectedLocationKind.PRIMARY_FAILURE,
    source_kind: SourceFileKind = SourceFileKind.PRODUCTION_SOURCE,
) -> AffectedSourceLocation:
    return AffectedSourceLocation(
        Path(file), line, kind, source_kind, EvidenceStrength.VERY_STRONG, "usage"
    )


def test_removed_method_plan_is_bounded_and_exposes_unverified_candidate() -> None:
    parse = member("parse", ("java.lang.String", "org.example.Options"))
    unrelated = member("close", ())
    bundle, diagnosis = _planning_inputs(
        new_class_members=(unrelated, parse),
    )
    locations = (
        _location(),
        _location(
            "src/main/java/com/example/Bar.java",
            20,
            AffectedLocationKind.POTENTIAL_CALL_SITE,
        ),
    )

    plan = MigrationPlanner().plan(bundle, diagnosis, locations)

    assert plan.status is PlanStatus.PLAN_READY
    assert plan.migration_kind is MigrationKind.REMOVED_METHOD
    assert plan.target_upgrade.artifact_id == "core"
    assert plan.target_upgrade.new_version == "2.0"
    assert plan.primary_source_location == locations[0]
    assert plan.allowed_files == (
        Path("src/main/java/com/example/Foo.java"),
        Path("src/main/java/com/example/Bar.java"),
    )
    assert [candidate.member.name for candidate in plan.new_api_candidates] == ["parse"]
    assert not plan.new_api_candidates[0].verified_replacement
    assert "parseValue" in plan.required_outcome
    assert plan.scope is PlanScope.SMALL
    assert set(BASE_REPAIR_CONSTRAINTS) <= set(plan.constraints)
    assert set(BASE_VERIFICATION_REQUIREMENTS) <= set(plan.verification_requirements)
    assert RepairConstraint.NO_TEST_DELETION in plan.constraints
    assert VerificationRequirement.TESTS_PASS in plan.verification_requirements


def test_signature_plan_identifies_parameter_type_without_value() -> None:
    bundle, diagnosis = _planning_inputs(
        ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE,
        new_class_members=(
            member("parseValue", ("java.lang.String", "org.example.Options")),
        ),
    )

    plan = MigrationPlanner().plan(bundle, diagnosis, (_location(),))

    assert plan.migration_kind is MigrationKind.CHANGED_METHOD_SIGNATURE
    assert plan.missing_parameter_types == ("org.example.Options",)
    assert "No argument values are selected" in plan.required_outcome
    assert "DEFAULT" not in plan.required_outcome


def test_overload_candidate_order_is_stable_and_prefers_fewer_new_parameters() -> None:
    bundle, _ = _planning_inputs()
    api = replace(
        bundle.api_evidence[0],
        old_members=(member("parse", ("java.lang.String",)),),
        failure_symbol="method parse(java.lang.String)",
        new_class_members=(
            member("parse", ("java.lang.String", "org.example.Options", "int")),
            member("parse", ("java.lang.String", "org.example.Options")),
            member("close", ()),
        ),
    )

    candidates = rank_api_candidates(api)

    assert [candidate.member.parameter_types for candidate in candidates] == [
        ("java.lang.String", "org.example.Options"),
        ("java.lang.String", "org.example.Options", "int"),
    ]
    assert all(not candidate.verified_replacement for candidate in candidates)


@pytest.mark.parametrize(
    ("api_kind", "migration_kind", "change"),
    [
        (ApiEvidenceKind.REMOVED_CLASS, MigrationKind.REMOVED_CLASS, None),
        (ApiEvidenceKind.PACKAGE_REMOVED, MigrationKind.REMOVED_PACKAGE, None),
        (
            ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS,
            MigrationKind.REMOVED_DEPENDENCY,
            removed_change(),
        ),
    ],
)
def test_removal_migration_kinds_are_preserved(
    api_kind, migration_kind, change
) -> None:
    bundle, diagnosis = _planning_inputs(api_kind, change=change)

    plan = MigrationPlanner().plan(bundle, diagnosis, (_location(),))

    assert plan.migration_kind is migration_kind
    assert plan.status is PlanStatus.PLAN_READY


def test_ambiguous_and_insufficient_diagnoses_are_not_actionable() -> None:
    bundle, supported = _planning_inputs()
    ambiguous = replace(supported, status=DiagnosisStatus.AMBIGUOUS_DIAGNOSIS)
    insufficient = replace(supported, status=DiagnosisStatus.INSUFFICIENT_EVIDENCE)

    ambiguous_plan = MigrationPlanner().plan(bundle, ambiguous, (_location(),))
    insufficient_plan = MigrationPlanner().plan(bundle, insufficient, (_location(),))

    assert ambiguous_plan.status is PlanStatus.NEEDS_HUMAN_REVIEW
    assert insufficient_plan.status is PlanStatus.NO_ACTIONABLE_DIAGNOSIS
    assert not ambiguous_plan.allowed_files
    assert not insufficient_plan.new_api_candidates


def test_unchanged_member_does_not_create_replacement_plan() -> None:
    bundle, diagnosis = _planning_inputs(ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED)

    plan = MigrationPlanner().plan(bundle, diagnosis, (_location(),))

    assert diagnosis.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert plan.status is PlanStatus.NO_ACTIONABLE_DIAGNOSIS
    assert plan.migration_kind is MigrationKind.UNKNOWN


def test_generated_primary_requires_human_review() -> None:
    bundle, diagnosis = _planning_inputs()
    generated = _location(
        "target/generated-sources/Foo.java",
        1,
        source_kind=SourceFileKind.GENERATED_SOURCE,
    )

    plan = MigrationPlanner().plan(bundle, diagnosis, (generated,))

    assert plan.status is PlanStatus.NEEDS_HUMAN_REVIEW
    assert not plan.allowed_files


def test_plan_without_localized_primary_is_partial() -> None:
    bundle, diagnosis = _planning_inputs()

    plan = MigrationPlanner().plan(bundle, diagnosis)

    assert plan.status is PlanStatus.PLAN_PARTIAL
    assert not plan.allowed_files


def test_initial_allowed_file_set_is_bounded() -> None:
    bundle, diagnosis = _planning_inputs()
    locations = (_location(),) + tuple(
        _location(
            f"src/main/java/com/example/Related{index:02}.java",
            1,
            AffectedLocationKind.POTENTIAL_CALL_SITE,
        )
        for index in range(25)
    )

    plan = MigrationPlanner().plan(bundle, diagnosis, locations)

    assert len(plan.allowed_files) == 20
    assert plan.scope is PlanScope.LARGE


@pytest.mark.parametrize(
    ("count", "scope"),
    [(1, PlanScope.SMALL), (4, PlanScope.MEDIUM), (6, PlanScope.LARGE)],
)
def test_scope_estimate_is_centralized(count: int, scope: PlanScope) -> None:
    assert estimate_scope(count) is scope


def test_allowed_paths_reject_escape() -> None:
    bundle, diagnosis = _planning_inputs()
    with pytest.raises(ValueError, match="repository-relative"):
        _location("../outside.java")


def test_repair_context_is_bounded_and_artifacts_are_deterministic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src/main/java/com/example/Foo.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class Foo {\n  void run() { parser.parseValue(value); }\n}\n",
        encoding="utf-8",
    )
    bundle, diagnosis = _planning_inputs(
        new_class_members=(member("parse", ("java.lang.String", "org.example.Options")),)
    )
    diagnosis = replace(diagnosis, artifact_directory=tmp_path)
    location = _location(line=2)
    plan = MigrationPlanner().plan(bundle, diagnosis, (location,))
    context = RepairContextBuilder().build(tmp_path, bundle, diagnosis, plan)

    artifacts = MigrationPlanArtifacts(tmp_path)
    artifacts.persist(plan, context)
    first = (tmp_path / "migration-plan.json").read_text(encoding="utf-8")
    artifacts.persist(plan, context)

    assert first == (tmp_path / "migration-plan.json").read_text(encoding="utf-8")
    assert MigrationPlanner().plan(bundle, diagnosis, (location,)) == plan
    assert migration_plan_to_dict(plan)["plan_id"] == plan.plan_id
    assert len(context.source_contexts) == 1
    assert set(path.name for path in tmp_path.glob("*.json")) == {
        "migration-plan.json",
        "repair-context.json",
    }
    serialized_context = json.loads(
        (tmp_path / "repair-context.json").read_text(encoding="utf-8")
    )
    assert "source_contexts" in serialized_context
    assert "maven_log" not in serialized_context
    assert (tmp_path / "migration-plan.txt").is_file()
