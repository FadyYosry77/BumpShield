import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bumpshield.agent.investigator import (
    CausalDiagnoser,
    DeterministicInvestigator,
    hypothesis_to_dict,
)
from bumpshield.models import (
    ApiEvidence,
    ApiEvidenceKind,
    ApiMatchStrategy,
    ApiMember,
    ApiMemberKind,
    CausalHypothesisKind,
    CausalStepKind,
    ClassOwnershipStatus,
    DependencyAttribution,
    DependencyChange,
    DependencyChangeKind,
    DependencyCoordinate,
    DependencyDiff,
    DependencyRelationship,
    DependencyUpgrade,
    DiagnosisStatus,
    EvidenceBundle,
    EvidenceReferenceKind,
    EvidenceStrength,
    FailureCategory,
    FailureSignal,
    HypothesisStatus,
    SourceContext,
    SourceLine,
    TaskSpec,
    TypeCandidate,
    TypeCandidateOrigin,
)


def coordinate(artifact: str, version: str) -> DependencyCoordinate:
    return DependencyCoordinate("org.example", artifact, version)


def updated_change(
    artifact: str = "parser",
    *,
    relationship: DependencyRelationship = DependencyRelationship.TRANSITIVE,
    is_target: bool = False,
    old_version: str = "1.0",
    new_version: str = "2.0",
) -> DependencyChange:
    return DependencyChange(
        DependencyChangeKind.UPDATED,
        relationship,
        before=coordinate(artifact, old_version),
        after=coordinate(artifact, new_version),
        is_target=is_target,
    )


def removed_change(artifact: str = "legacy") -> DependencyChange:
    return DependencyChange(
        DependencyChangeKind.REMOVED,
        DependencyRelationship.TRANSITIVE,
        before=coordinate(artifact, "1.0"),
    )


def member(name: str, parameters: tuple[str, ...]) -> ApiMember:
    joined = ", ".join(parameters)
    return ApiMember(
        ApiMemberKind.METHOD,
        name,
        f"public java.lang.Object {name}({joined});",
        parameters,
        "java.lang.Object",
    )


def make_bundle(
    api_kind: ApiEvidenceKind = ApiEvidenceKind.REMOVED_MEMBER,
    *,
    change: DependencyChange | None = None,
    target_on_path: bool = True,
    ownership: ClassOwnershipStatus = ClassOwnershipStatus.EXACT_SINGLE_MATCH,
    dependencies: tuple[DependencyChange, ...] | None = None,
    with_context: bool = True,
    category: FailureCategory = FailureCategory.MISSING_SYMBOL,
    symbol: str = "method parseValue(java.lang.String)",
) -> EvidenceBundle:
    actual_change = change or updated_change()
    failure = FailureSignal(
        category,
        "cannot find symbol",
        file=Path("src/main/java/com/example/Foo.java"),
        line=84,
        symbol=symbol,
    )
    old_members = (member("parseValue", ("java.lang.String",)),)
    new_members: tuple[ApiMember, ...] = ()
    if api_kind is ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED:
        new_members = old_members
    elif api_kind is ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE:
        new_members = (
            member("parseValue", ("java.lang.String", "org.example.Options")),
        )
    api = ApiEvidence(
        api_kind,
        "org.example.parser.Parser",
        symbol,
        actual_change.before,
        actual_change.after,
        True,
        False if api_kind in {
            ApiEvidenceKind.REMOVED_CLASS,
            ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS,
            ApiEvidenceKind.PACKAGE_REMOVED,
        } else True,
        old_members=old_members,
        new_members=new_members,
        match_strategy=ApiMatchStrategy.EXACT_PARAMETERS,
    )
    path = (
        coordinate(
            "core",
            "1.0"
            if actual_change.kind is DependencyChangeKind.REMOVED
            else "2.0",
        ),
        actual_change.after or actual_change.before,
    )
    contexts = (
        SourceContext(
            Path("src/main/java/com/example/Foo.java"),
            84,
            84,
            84,
            (SourceLine(84, 'return parser.parseValue("x");'),),
            package="com.example",
            imports=("org.example.parser.Parser",),
        ),
    ) if with_context else ()
    attribution = DependencyAttribution(
        TypeCandidate(
            "org.example.parser.Parser", TypeCandidateOrigin.COMPILER_TYPE
        ),
        ownership,
        dependencies=dependencies if dependencies is not None else (actual_change,),
        dependency_path=path if target_on_path else (actual_change.after or actual_change.before,),
        target_on_path=target_on_path,
        api_evidence=(api,) if ownership is ClassOwnershipStatus.EXACT_SINGLE_MATCH else (),
    )
    return EvidenceBundle(
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
        run_id="diagnosis-run",
        artifact_directory=Path("/external/state/runs/diagnosis-run"),
        dependency_diff=DependencyDiff((actual_change,)),
        failures=(failure,),
        source_contexts=contexts,
        dependency_attributions=(attribution,),
        api_evidence=(api,),
    )


def test_removed_member_builds_very_strong_transitive_causal_chain() -> None:
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(change=updated_change(old_version="4.0", new_version="5.0"))
    )

    assert diagnosis.status is DiagnosisStatus.SUPPORTED_DIAGNOSIS
    hypothesis = diagnosis.primary_hypothesis
    assert hypothesis is not None
    assert hypothesis.kind is CausalHypothesisKind.REMOVED_MEMBER
    assert hypothesis.status is HypothesisStatus.SUPPORTED
    assert hypothesis.evidence_strength is EvidenceStrength.VERY_STRONG
    assert hypothesis.evidence_score == 100
    assert [step.kind for step in hypothesis.causal_chain] == [
        CausalStepKind.TARGET_UPGRADE,
        CausalStepKind.DEPENDENCY_RESOLUTION_CHANGE,
        CausalStepKind.API_CHANGE,
        CausalStepKind.PROJECT_USAGE,
        CausalStepKind.OBSERVED_FAILURE,
    ]
    assert hypothesis.target_on_path
    assert hypothesis.implicated_dependencies[0].relationship is DependencyRelationship.TRANSITIVE
    assert hypothesis.implicated_dependencies[0].before.version == "4.0"
    assert hypothesis.implicated_dependencies[0].after.version == "5.0"


def test_direct_target_api_change_omits_transitive_resolution_step() -> None:
    change = updated_change(
        "core", relationship=DependencyRelationship.DIRECT, is_target=True
    )
    hypothesis = DeterministicInvestigator().investigate(
        make_bundle(change=change)
    ).primary_hypothesis

    assert hypothesis is not None
    assert [step.kind for step in hypothesis.causal_chain] == [
        CausalStepKind.TARGET_UPGRADE,
        CausalStepKind.API_CHANGE,
        CausalStepKind.PROJECT_USAGE,
        CausalStepKind.OBSERVED_FAILURE,
    ]
    assert hypothesis.implicated_dependencies[0].is_target


def test_signature_change_preserves_old_and_new_declarations() -> None:
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(
            ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE,
            category=FailureCategory.METHOD_ARGUMENT_MISMATCH,
        )
    )

    hypothesis = diagnosis.primary_hypothesis
    assert hypothesis is not None
    assert hypothesis.kind is CausalHypothesisKind.CHANGED_MEMBER_SIGNATURE
    api_reference = next(
        item for item in hypothesis.supporting_evidence
        if item.kind is EvidenceReferenceKind.API_CHANGE
    )
    assert "java.lang.String" in api_reference.detail
    assert "org.example.Options" in api_reference.detail


@pytest.mark.parametrize(
    ("api_kind", "expected_kind", "change"),
    [
        (
            ApiEvidenceKind.REMOVED_CLASS,
            CausalHypothesisKind.REMOVED_CLASS,
            updated_change(),
        ),
        (
            ApiEvidenceKind.PACKAGE_REMOVED,
            CausalHypothesisKind.REMOVED_PACKAGE,
            updated_change(),
        ),
        (
            ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS,
            CausalHypothesisKind.REMOVED_DEPENDENCY,
            removed_change(),
        ),
    ],
)
def test_class_package_and_dependency_removals_are_distinct(
    api_kind: ApiEvidenceKind,
    expected_kind: CausalHypothesisKind,
    change: DependencyChange,
) -> None:
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(api_kind, change=change)
    )
    assert diagnosis.primary_hypothesis is not None
    assert diagnosis.primary_hypothesis.kind is expected_kind


def test_unchanged_member_is_a_hard_contradiction() -> None:
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED)
    )

    assert diagnosis.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert diagnosis.primary_hypothesis is None
    candidate = diagnosis.hypotheses[0]
    assert candidate.status is HypothesisStatus.CONTRADICTED
    assert candidate.evidence_score <= 20
    assert candidate.contradictory_evidence[0].kind is EvidenceReferenceKind.RELEVANT_MEMBER_UNCHANGED


def test_unavailable_api_is_missing_not_contradictory_evidence() -> None:
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(ApiEvidenceKind.API_INSPECTION_UNAVAILABLE)
    )

    candidate = diagnosis.hypotheses[0]
    assert diagnosis.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert candidate.contradictory_evidence == ()
    assert any(
        item.kind is EvidenceReferenceKind.API_INSPECTION_UNAVAILABLE
        for item in candidate.missing_evidence
    )


def test_missing_source_context_lowers_complete_api_chain_to_partial() -> None:
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(with_context=False)
    )

    candidate = diagnosis.primary_hypothesis
    assert diagnosis.status is DiagnosisStatus.PARTIAL_DIAGNOSIS
    assert candidate is not None
    assert any(
        item.kind is EvidenceReferenceKind.SOURCE_UNRESOLVED
        for item in candidate.missing_evidence
    )

def test_ambiguous_ownership_never_selects_a_primary_dependency() -> None:
    changes = (updated_change("alpha"), updated_change("beta"))
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(
            ownership=ClassOwnershipStatus.MULTIPLE_MATCHES,
            dependencies=changes,
        )
    )

    assert diagnosis.status is DiagnosisStatus.AMBIGUOUS_DIAGNOSIS
    assert diagnosis.primary_hypothesis is None
    assert diagnosis.hypotheses[0].status is HypothesisStatus.AMBIGUOUS
    assert diagnosis.hypotheses[0].implicated_dependencies == changes


def test_dependency_outside_target_subtree_is_partial_without_target_claim() -> None:
    diagnosis = DeterministicInvestigator().investigate(
        make_bundle(target_on_path=False)
    )

    hypothesis = diagnosis.primary_hypothesis
    assert diagnosis.status is DiagnosisStatus.PARTIAL_DIAGNOSIS
    assert hypothesis is not None
    assert not hypothesis.target_on_path
    assert CausalStepKind.TARGET_UPGRADE not in {
        step.kind for step in hypothesis.causal_chain
    }
    assert "not connected" in hypothesis.explanation


def test_inconsistent_phase_evidence_cannot_become_supported() -> None:
    bundle = make_bundle()
    bundle = EvidenceBundle(
        bundle.target_upgrade,
        run_id=bundle.run_id,
        artifact_directory=bundle.artifact_directory,
        dependency_diff=DependencyDiff(),
        failures=bundle.failures,
        source_contexts=bundle.source_contexts,
        dependency_attributions=bundle.dependency_attributions,
    )

    diagnosis = DeterministicInvestigator().investigate(bundle)

    assert diagnosis.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
    candidate = diagnosis.hypotheses[0]
    assert candidate.status is HypothesisStatus.CONTRADICTED
    assert any(
        item.kind is EvidenceReferenceKind.EVIDENCE_INCONSISTENCY
        for item in candidate.contradictory_evidence
    )


def test_version_change_or_import_without_api_fact_produces_no_hypothesis() -> None:
    bundle = make_bundle()
    attribution = bundle.dependency_attributions[0]
    bundle = EvidenceBundle(
        bundle.target_upgrade,
        run_id=bundle.run_id,
        artifact_directory=bundle.artifact_directory,
        dependency_diff=bundle.dependency_diff,
        failures=bundle.failures,
        source_contexts=bundle.source_contexts,
        dependency_attributions=(
            DependencyAttribution(
                attribution.candidate,
                attribution.ownership,
                attribution.dependencies,
                attribution.dependency_path,
                attribution.target_on_path,
                (),
            ),
        ),
    )

    diagnosis = DeterministicInvestigator().investigate(bundle)
    assert diagnosis.status is DiagnosisStatus.INSUFFICIENT_EVIDENCE
    assert diagnosis.hypotheses == ()


def test_ranking_and_serialization_are_stable_and_non_probabilistic() -> None:
    bundle = make_bundle()
    first = bundle.dependency_attributions[0]
    second_change = updated_change("zeta")
    second_api = ApiEvidence(
        ApiEvidenceKind.REMOVED_MEMBER,
        first.candidate.name,
        bundle.primary_failure.symbol,
        second_change.before,
        second_change.after,
        True,
        True,
        old_members=first.api_evidence[0].old_members,
    )
    second = DependencyAttribution(
        first.candidate,
        ClassOwnershipStatus.EXACT_SINGLE_MATCH,
        (second_change,),
        (coordinate("core", "2.0"), second_change.after),
        True,
        (second_api,),
    )
    combined = EvidenceBundle(
        bundle.target_upgrade,
        run_id=bundle.run_id,
        artifact_directory=bundle.artifact_directory,
        dependency_diff=DependencyDiff((second_change, first.dependencies[0])),
        failures=bundle.failures,
        source_contexts=bundle.source_contexts,
        dependency_attributions=(second, first),
    )

    left = DeterministicInvestigator().investigate(combined)
    right = DeterministicInvestigator().investigate(combined)
    assert [item.id for item in left.hypotheses] == [item.id for item in right.hypotheses]
    assert [item.rank for item in left.hypotheses] == [1, 2]
    serialized = json.dumps(hypothesis_to_dict(left.hypotheses[0])).lower()
    assert json.dumps(
        [hypothesis_to_dict(item) for item in left.hypotheses], sort_keys=True
    ) == json.dumps(
        [hypothesis_to_dict(item) for item in right.hypotheses], sort_keys=True
    )
    assert "probability" not in serialized
    assert "confidence" not in serialized


def test_hard_contradiction_ranks_below_consistent_api_evidence() -> None:
    contradicted_bundle = make_bundle(
        ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED,
        change=updated_change("alpha"),
    )
    supported_bundle = make_bundle(change=updated_change("zeta"))
    changes = (
        contradicted_bundle.dependency_attributions[0].dependencies[0],
        supported_bundle.dependency_attributions[0].dependencies[0],
    )
    combined = EvidenceBundle(
        supported_bundle.target_upgrade,
        run_id="rank-run",
        artifact_directory=Path("/external/state/runs/rank-run"),
        dependency_diff=DependencyDiff(changes),
        failures=supported_bundle.failures,
        source_contexts=supported_bundle.source_contexts,
        dependency_attributions=(
            contradicted_bundle.dependency_attributions[0],
            supported_bundle.dependency_attributions[0],
        ),
    )

    diagnosis = DeterministicInvestigator().investigate(combined)

    assert diagnosis.hypotheses[0].status is HypothesisStatus.SUPPORTED
    assert diagnosis.hypotheses[0].implicated_dependencies[0].after.artifact_id == "zeta"
    assert diagnosis.hypotheses[1].status is HypothesisStatus.CONTRADICTED


class FakeEvidenceAnalyzer:
    def __init__(self, bundle: EvidenceBundle, path: Path) -> None:
        self.bundle = bundle
        self.path = path

    def analyze(self, task: TaskSpec, run_id: str | None = None) -> object:
        return SimpleNamespace(
            evidence_bundle=self.bundle,
            artifact_directory=self.path,
        )


def test_diagnoser_appends_artifacts_to_existing_external_run(tmp_path: Path) -> None:
    run_path = tmp_path / "state" / "runs" / "diagnosis-run"
    run_path.mkdir(parents=True)
    (run_path / "evidence-bundle.json").write_text("{}\n", encoding="utf-8")
    bundle = make_bundle()
    bundle = EvidenceBundle(
        bundle.target_upgrade,
        run_id=bundle.run_id,
        artifact_directory=run_path,
        dependency_diff=bundle.dependency_diff,
        failures=bundle.failures,
        source_contexts=bundle.source_contexts,
        dependency_attributions=bundle.dependency_attributions,
    )
    task = TaskSpec(
        tmp_path / "repository",
        "base",
        "updated",
        bundle.target_upgrade,
    )

    diagnosis = CausalDiagnoser(
        evidence_analyzer=FakeEvidenceAnalyzer(bundle, run_path)
    ).diagnose(task)

    assert diagnosis.status is DiagnosisStatus.SUPPORTED_DIAGNOSIS
    assert (run_path / "evidence-bundle.json").read_text() == "{}\n"
    assert {
        "hypotheses.json",
        "causal-diagnosis.json",
        "diagnosis.txt",
    } <= {item.name for item in run_path.iterdir()}
    metadata = json.loads((run_path / "causal-diagnosis.json").read_text())
    assert metadata["primary_hypothesis_id"] == diagnosis.primary_hypothesis.id
    assert "SUPPORTED_DIAGNOSIS" in (run_path / "diagnosis.txt").read_text()
