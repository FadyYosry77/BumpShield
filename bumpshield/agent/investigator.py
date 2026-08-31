"""Deterministic causal hypotheses constructed from Phase 4 evidence."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from bumpshield.analysis.api_diff import ApiEvidenceAnalysisError, ApiEvidenceAnalyzer
from bumpshield.config import BumpShieldConfig
from bumpshield.models import (
    ApiEvidence,
    ApiEvidenceAnalysisResult,
    ApiEvidenceKind,
    CausalDiagnosis,
    CausalHypothesisKind,
    CausalStep,
    CausalStepKind,
    ClassOwnershipStatus,
    DependencyAttribution,
    DependencyChange,
    DependencyChangeKind,
    DependencyCoordinate,
    DiagnosisRun,
    DiagnosisStatus,
    EvidenceBundle,
    EvidenceReference,
    EvidenceReferenceKind,
    EvidenceStrength,
    FailureSignal,
    HypothesisStatus,
    RootCauseHypothesis,
    SourceContext,
    TaskSpec,
)
from bumpshield.run import RunSetupError, require_external_path


# Each value is an auditable contribution to an ordinal evidence score. The
# score ranks deterministic evidence chains; it is deliberately not a probability.
EVIDENCE_WEIGHTS: Mapping[str, int] = MappingProxyType({
    "DEPENDENCY_VERSION_CHANGE": 10,  # observed Phase 2 transition
    "EXACT_CLASS_OWNERSHIP": 20,  # unique Phase 4 JAR owner
    "CONCRETE_API_CHANGE": 30,  # strongest old/new API fact
    "EXACT_FAILURE_SYMBOL_MATCH": 20,  # joins failure to API fact
    "SOURCE_LOCALIZED": 5,  # failure maps to project source
    "EXACT_SOURCE_CALL_SITE": 5,  # focus line contains symbol token
    "VALID_TARGET_PATH": 10,  # real graph path joins target to owner
    "AMBIGUOUS_OWNERSHIP_PENALTY": -40,  # no unique owner
    "API_INSPECTION_MISSING_PENALTY": -35,  # API transition unknown
    "INCOMPLETE_TARGET_PATH_PENALTY": -10,  # no target provenance
    "SOURCE_UNRESOLVED_PENALTY": -10,  # no project usage location
})
HARD_CONTRADICTION_SCORE_CAP = 20
LOGGER = logging.getLogger(__name__)

_POSITIVE_API_KINDS = {
    ApiEvidenceKind.REMOVED_MEMBER,
    ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE,
    ApiEvidenceKind.REMOVED_CLASS,
    ApiEvidenceKind.PACKAGE_REMOVED,
    ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS,
}
_HYPOTHESIS_KINDS = {
    ApiEvidenceKind.REMOVED_MEMBER: CausalHypothesisKind.REMOVED_MEMBER,
    ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE:
        CausalHypothesisKind.CHANGED_MEMBER_SIGNATURE,
    ApiEvidenceKind.REMOVED_CLASS: CausalHypothesisKind.REMOVED_CLASS,
    ApiEvidenceKind.PACKAGE_REMOVED: CausalHypothesisKind.REMOVED_PACKAGE,
    ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS:
        CausalHypothesisKind.REMOVED_DEPENDENCY,
    ApiEvidenceKind.API_INSPECTION_UNAVAILABLE:
        CausalHypothesisKind.API_INSPECTION_UNAVAILABLE,
    ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED:
        CausalHypothesisKind.RELEVANT_MEMBER_UNCHANGED,
}


class DiagnosisError(RuntimeError):
    """Raised when trustworthy diagnosis orchestration cannot complete."""


class EvidenceAnalysis(Protocol):
    """Small Phase 4 service boundary consumed by diagnosis orchestration."""

    def analyze(
        self, task: TaskSpec, run_id: str | None = None
    ) -> ApiEvidenceAnalysisResult:
        """Return one persisted Phase 4 analysis result."""


class Investigator(Protocol):
    """Replaceable pure causal-investigation boundary."""

    def investigate(self, evidence: EvidenceBundle) -> CausalDiagnosis:
        """Construct a diagnosis without external commands or state mutation."""


class DeterministicInvestigator:
    """Build and rank explicit causal chains from a typed evidence bundle."""

    def investigate(self, evidence: EvidenceBundle) -> CausalDiagnosis:
        run_id = evidence.run_id or "unpersisted"
        artifact_directory = evidence.artifact_directory or Path(".")
        candidates: list[RootCauseHypothesis] = []
        for attribution in evidence.dependency_attributions:
            candidates.extend(self._from_attribution(evidence, attribution))

        ordered = sorted(candidates, key=_hypothesis_sort_key)
        ranked = tuple(
            replace(candidate, rank=index)
            for index, candidate in enumerate(ordered, start=1)
        )
        status = _diagnosis_status(ranked)
        unresolved = _unresolved_questions(status, ranked, evidence)
        LOGGER.debug(
            "constructed %d hypotheses (%s); diagnosis=%s primary=%s",
            len(ranked),
            ", ".join(item.kind.value for item in ranked) or "none",
            status.value,
            ranked[0].id if ranked else "none",
        )
        return CausalDiagnosis(
            run_id=run_id,
            status=status,
            artifact_directory=artifact_directory,
            hypotheses=ranked,
            summary=_diagnosis_summary(status, ranked),
            unresolved_questions=unresolved,
        )

    def _from_attribution(
        self,
        bundle: EvidenceBundle,
        attribution: DependencyAttribution,
    ) -> list[RootCauseHypothesis]:
        failure = bundle.primary_failure
        if attribution.ownership is ClassOwnershipStatus.MULTIPLE_MATCHES:
            return [self._ambiguous_hypothesis(attribution, failure)]
        if attribution.ownership is not ClassOwnershipStatus.EXACT_SINGLE_MATCH:
            return []
        return [
            self._api_hypothesis(bundle, attribution, failure, api)
            for api in attribution.api_evidence
            if api.kind in _HYPOTHESIS_KINDS
        ]

    def _ambiguous_hypothesis(
        self,
        attribution: DependencyAttribution,
        failure: FailureSignal | None,
    ) -> RootCauseHypothesis:
        ownership = _reference(
            EvidenceReferenceKind.AMBIGUOUS_CLASS_OWNERSHIP,
            f"{attribution.candidate.name} occurs in multiple changed dependencies",
            "class-attribution.json",
        )
        missing = _reference(
            EvidenceReferenceKind.API_INSPECTION_UNAVAILABLE,
            "ownership ambiguity prevents a unique old/new API comparison",
            "api-evidence.json",
        )
        score = max(0, EVIDENCE_WEIGHTS["AMBIGUOUS_OWNERSHIP_PENALTY"])
        dependency_names = ", ".join(
            _dependency_identity(item) for item in attribution.dependencies
        )
        summary = (
            f"{attribution.candidate.name} has ambiguous ownership across "
            f"{dependency_names or 'changed dependencies'}"
        )
        hypothesis_id = _hypothesis_id(
            CausalHypothesisKind.AMBIGUOUS_OWNERSHIP,
            attribution,
            failure,
        )
        return RootCauseHypothesis(
            id=hypothesis_id,
            rank=0,
            status=HypothesisStatus.AMBIGUOUS,
            kind=CausalHypothesisKind.AMBIGUOUS_OWNERSHIP,
            summary=summary,
            implicated_dependencies=attribution.dependencies,
            dependency_path=(),
            target_on_path=False,
            failure=failure,
            causal_chain=(),
            supporting_evidence=(ownership,),
            contradictory_evidence=(),
            missing_evidence=(missing,),
            evidence_strength=_strength(score),
            evidence_score=score,
            explanation=(
                "The available class-ownership evidence does not uniquely identify "
                "one changed dependency, so no causal dependency is selected."
            ),
        )

    def _api_hypothesis(
        self,
        bundle: EvidenceBundle,
        attribution: DependencyAttribution,
        failure: FailureSignal | None,
        api: ApiEvidence,
    ) -> RootCauseHypothesis:
        kind = _HYPOTHESIS_KINDS[api.kind]
        supporting: list[EvidenceReference] = []
        contradictory: list[EvidenceReference] = []
        missing: list[EvidenceReference] = []
        score = 0

        inconsistencies = _evidence_inconsistencies(
            bundle, attribution, failure, api
        )
        contradictory.extend(
            _reference(
                EvidenceReferenceKind.EVIDENCE_INCONSISTENCY,
                detail,
                "evidence-bundle.json",
            )
            for detail in inconsistencies
        )

        if attribution.dependencies:
            supporting.append(
                _reference(
                    EvidenceReferenceKind.DEPENDENCY_UPDATE,
                    _dependency_change_detail(attribution.dependencies[0]),
                    "dependency-diff.json",
                )
            )
            score += EVIDENCE_WEIGHTS["DEPENDENCY_VERSION_CHANGE"]
        supporting.append(
            _reference(
                EvidenceReferenceKind.EXACT_CLASS_OWNERSHIP,
                f"{attribution.candidate.name} has one changed dependency owner",
                "class-attribution.json",
            )
        )
        score += EVIDENCE_WEIGHTS["EXACT_CLASS_OWNERSHIP"]

        if api.kind in _POSITIVE_API_KINDS:
            supporting.append(
                _reference(
                    EvidenceReferenceKind.API_CHANGE,
                    _api_change_description(api),
                    "api-evidence.json",
                )
            )
            score += EVIDENCE_WEIGHTS["CONCRETE_API_CHANGE"]
        elif api.kind is ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED:
            contradictory.append(
                _reference(
                    EvidenceReferenceKind.RELEVANT_MEMBER_UNCHANGED,
                    _api_change_description(api),
                    "api-evidence.json",
                )
            )
        elif api.kind is ApiEvidenceKind.API_INSPECTION_UNAVAILABLE:
            missing.append(
                _reference(
                    EvidenceReferenceKind.API_INSPECTION_UNAVAILABLE,
                    "old/new API inspection did not complete",
                    "api-evidence.json",
                )
            )
            score += EVIDENCE_WEIGHTS["API_INSPECTION_MISSING_PENALTY"]

        if failure and api.failure_symbol and api.failure_symbol == failure.symbol:
            supporting.append(
                _reference(
                    EvidenceReferenceKind.FAILURE_SYMBOL_MATCH,
                    f"failure symbol matches API evidence: {api.failure_symbol}",
                    "failures.json",
                )
            )
            score += EVIDENCE_WEIGHTS["EXACT_FAILURE_SYMBOL_MATCH"]
        elif not failure or not api.failure_symbol:
            missing.append(
                _reference(
                    EvidenceReferenceKind.FAILURE_SYMBOL_MATCH,
                    "no exact failure symbol is available for the API fact",
                    "failures.json",
                )
            )

        context = _matching_context(bundle.source_contexts, failure)
        if context is None:
            missing.append(
                _reference(
                    EvidenceReferenceKind.SOURCE_UNRESOLVED,
                    "the primary failure has no matching localized source context",
                    "source-contexts.json",
                )
            )
            score += EVIDENCE_WEIGHTS["SOURCE_UNRESOLVED_PENALTY"]
        else:
            supporting.append(
                _reference(
                    EvidenceReferenceKind.SOURCE_LOCALIZED,
                    _source_location(failure),
                    "source-contexts.json",
                )
            )
            score += EVIDENCE_WEIGHTS["SOURCE_LOCALIZED"]
            if _exact_call_site(context, failure, api):
                supporting.append(
                    _reference(
                        EvidenceReferenceKind.SOURCE_CALL_SITE,
                        f"localized source contains the failing symbol {failure.symbol}",
                        "source-contexts.json",
                    )
                )
                score += EVIDENCE_WEIGHTS["EXACT_SOURCE_CALL_SITE"]

        if attribution.target_on_path:
            supporting.append(
                _reference(
                    EvidenceReferenceKind.TARGET_DEPENDENCY_PATH,
                    _path_detail(attribution.dependency_path),
                    "dependencies-after.json"
                    if api.after is not None
                    else "dependencies-before.json",
                )
            )
            score += EVIDENCE_WEIGHTS["VALID_TARGET_PATH"]
        else:
            missing.append(
                _reference(
                    EvidenceReferenceKind.DEPENDENCY_PATH_INCOMPLETE,
                    "the changed dependency is not connected to the requested target",
                    "dependency-diff.json",
                )
            )
            score += EVIDENCE_WEIGHTS["INCOMPLETE_TARGET_PATH_PENALTY"]

        score = max(0, min(100, score))
        if contradictory:
            score = min(score, HARD_CONTRADICTION_SCORE_CAP)
            status = HypothesisStatus.CONTRADICTED
        elif api.kind is ApiEvidenceKind.API_INSPECTION_UNAVAILABLE:
            status = HypothesisStatus.INSUFFICIENT_EVIDENCE
        elif api.kind in _POSITIVE_API_KINDS and missing:
            status = HypothesisStatus.PARTIALLY_SUPPORTED
        elif api.kind in _POSITIVE_API_KINDS:
            status = HypothesisStatus.SUPPORTED
        else:
            status = HypothesisStatus.INSUFFICIENT_EVIDENCE

        summary = _hypothesis_summary(kind, attribution, api)
        causal_chain = _causal_chain(
            bundle,
            attribution,
            failure,
            api,
            tuple(supporting),
            context,
        )
        return RootCauseHypothesis(
            id=_hypothesis_id(kind, attribution, failure),
            rank=0,
            status=status,
            kind=kind,
            summary=summary,
            implicated_dependencies=attribution.dependencies,
            dependency_path=attribution.dependency_path,
            target_on_path=attribution.target_on_path,
            failure=failure,
            causal_chain=causal_chain,
            supporting_evidence=tuple(supporting),
            contradictory_evidence=tuple(contradictory),
            missing_evidence=tuple(missing),
            evidence_strength=_strength(score),
            evidence_score=score,
            explanation=_explanation(status, summary, attribution.target_on_path),
        )


class CausalDiagnoser:
    """Compose Phase 4 once, run pure investigation, and append artifacts."""

    def __init__(
        self,
        evidence_analyzer: EvidenceAnalysis | None = None,
        investigator: Investigator | None = None,
        config: BumpShieldConfig | None = None,
    ) -> None:
        self.config = config or BumpShieldConfig()
        self.evidence_analyzer = evidence_analyzer or ApiEvidenceAnalyzer(
            config=self.config
        )
        self.investigator = investigator or DeterministicInvestigator()

    def diagnose(
        self, task: TaskSpec, run_id: str | None = None
    ) -> CausalDiagnosis:
        """Return diagnosis while retaining compatibility with Phase 5 callers."""
        return self.diagnose_run(task, run_id=run_id).diagnosis

    def diagnose_run(
        self, task: TaskSpec, run_id: str | None = None
    ) -> DiagnosisRun:
        """Return diagnosis paired with the exact evidence bundle it consumed."""
        try:
            evidence_result = self.evidence_analyzer.analyze(task, run_id=run_id)
        except ApiEvidenceAnalysisError as error:
            raise DiagnosisError(str(error)) from error
        bundle = evidence_result.evidence_bundle
        if bundle is None:
            raise DiagnosisError("Phase 4 analysis did not provide an evidence bundle")
        artifact_directory = Path(evidence_result.artifact_directory).resolve()
        try:
            require_external_path(artifact_directory, task.repository.resolve())
        except RunSetupError as error:
            raise DiagnosisError(str(error)) from error
        if not artifact_directory.is_dir():
            raise DiagnosisError(
                f"Phase 4 artifact directory does not exist: {artifact_directory}"
            )
        diagnosis = self.investigator.investigate(bundle)
        if diagnosis.artifact_directory.resolve() != artifact_directory:
            raise DiagnosisError(
                "diagnosis artifact directory disagrees with Phase 4 run directory"
            )
        try:
            DiagnosisArtifacts(artifact_directory).persist(diagnosis)
        except OSError as error:
            raise DiagnosisError(f"could not persist diagnosis artifacts: {error}") from error
        return DiagnosisRun(task=task, evidence=bundle, diagnosis=diagnosis)


class DiagnosisArtifacts:
    """Persist only Phase 5 outputs beside the retained Phase 4 evidence."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def persist(self, diagnosis: CausalDiagnosis) -> None:
        self._write_json(
            "hypotheses.json",
            [hypothesis_to_dict(item) for item in diagnosis.hypotheses],
        )
        primary = diagnosis.primary_hypothesis
        self._write_json(
            "causal-diagnosis.json",
            {
                "run_id": diagnosis.run_id,
                "status": diagnosis.status.value,
                "primary_hypothesis_id": primary.id if primary else None,
                "ordered_hypothesis_ids": [
                    item.id for item in diagnosis.hypotheses
                ],
                "summary": diagnosis.summary,
                "unresolved_questions": list(diagnosis.unresolved_questions),
            },
        )
        (self.path / "diagnosis.txt").write_text(
            diagnosis_report(diagnosis), encoding="utf-8"
        )

    def _write_json(self, filename: str, value: object) -> None:
        (self.path / filename).write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )


def hypothesis_to_dict(hypothesis: RootCauseHypothesis) -> dict[str, object]:
    """Serialize one hypothesis canonically without probabilistic terminology."""
    return {
        "id": hypothesis.id,
        "rank": hypothesis.rank,
        "status": hypothesis.status.value,
        "kind": hypothesis.kind.value,
        "summary": hypothesis.summary,
        "implicated_dependencies": [
            _change_to_dict(item) for item in hypothesis.implicated_dependencies
        ],
        "dependency_path": [
            _coordinate_to_dict(item) for item in hypothesis.dependency_path
        ],
        "target_on_path": hypothesis.target_on_path,
        "failure": _failure_to_dict(hypothesis.failure),
        "causal_chain": [
            {
                "order": step.order,
                "kind": step.kind.value,
                "description": step.description,
                "evidence_ids": list(step.evidence_ids),
            }
            for step in hypothesis.causal_chain
        ],
        "supporting_evidence": [
            _reference_to_dict(item) for item in hypothesis.supporting_evidence
        ],
        "contradictory_evidence": [
            _reference_to_dict(item) for item in hypothesis.contradictory_evidence
        ],
        "missing_evidence": [
            _reference_to_dict(item) for item in hypothesis.missing_evidence
        ],
        "evidence_strength": hypothesis.evidence_strength.value,
        "evidence_score": hypothesis.evidence_score,
        "explanation": hypothesis.explanation,
    }


def diagnosis_report(diagnosis: CausalDiagnosis) -> str:
    """Render concise deterministic prose entirely from diagnosis fields."""
    lines = [
        "BumpShield Causal Diagnosis",
        "===========================",
        "",
        f"Run: {diagnosis.run_id}",
        f"Status: {diagnosis.status.value}",
        f"Summary: {diagnosis.summary}",
    ]
    primary = diagnosis.primary_hypothesis
    if primary is not None:
        lines.extend(
            [
                "",
                f"Primary Hypothesis: {primary.id}",
                f"Evidence: {primary.evidence_strength.value} "
                f"({primary.evidence_score}/100)",
                primary.explanation,
                "",
                "Causal Chain:",
            ]
        )
        lines.extend(f"{step.order}. {step.description}" for step in primary.causal_chain)
        lines.extend(["", "Supporting Evidence:"])
        lines.extend(f"- {item.detail}" for item in primary.supporting_evidence)
        lines.extend(["", "Contradictory Evidence:"])
        lines.extend(
            [f"- {item.detail}" for item in primary.contradictory_evidence]
            or ["- none"]
        )
    elif diagnosis.hypotheses:
        lines.extend(["", "Candidates:"])
        lines.extend(
            f"- {item.id}: {item.status.value}: {item.summary}"
            for item in diagnosis.hypotheses[:3]
        )
    if diagnosis.unresolved_questions:
        lines.extend(["", "Unresolved:"])
        lines.extend(f"- {item}" for item in diagnosis.unresolved_questions)
    return "\n".join(lines) + "\n"


def _causal_chain(
    bundle: EvidenceBundle,
    attribution: DependencyAttribution,
    failure: FailureSignal | None,
    api: ApiEvidence,
    references: tuple[EvidenceReference, ...],
    context: SourceContext | None,
) -> tuple[CausalStep, ...]:
    reference_by_kind = {item.kind: item.id for item in references}
    steps: list[tuple[CausalStepKind, str, tuple[str, ...]]] = []
    change = attribution.dependencies[0] if attribution.dependencies else None
    if change and change.is_target and attribution.target_on_path:
        steps.append(
            (
                CausalStepKind.TARGET_UPGRADE,
                _target_upgrade_detail(bundle),
                _ids(reference_by_kind, EvidenceReferenceKind.DEPENDENCY_UPDATE),
            )
        )
    elif change and attribution.target_on_path:
        steps.append(
            (
                CausalStepKind.TARGET_UPGRADE,
                _target_upgrade_detail(bundle),
                _ids(reference_by_kind, EvidenceReferenceKind.TARGET_DEPENDENCY_PATH),
            )
        )
        steps.append(
            (
                CausalStepKind.DEPENDENCY_RESOLUTION_CHANGE,
                _dependency_change_detail(change),
                _ids(reference_by_kind, EvidenceReferenceKind.DEPENDENCY_UPDATE),
            )
        )
    elif change:
        steps.append(
            (
                CausalStepKind.DEPENDENCY_RESOLUTION_CHANGE,
                _dependency_change_detail(change),
                _ids(reference_by_kind, EvidenceReferenceKind.DEPENDENCY_UPDATE),
            )
        )
    if api.kind in _POSITIVE_API_KINDS:
        steps.append(
            (
                CausalStepKind.API_CHANGE,
                _api_change_description(api),
                _ids(reference_by_kind, EvidenceReferenceKind.API_CHANGE),
            )
        )
    if context is not None and failure is not None:
        steps.append(
            (
                CausalStepKind.PROJECT_USAGE,
                f"project source at {_source_location(failure)} uses "
                f"{failure.symbol or api.class_name}",
                _ids(
                    reference_by_kind,
                    EvidenceReferenceKind.SOURCE_CALL_SITE,
                    EvidenceReferenceKind.SOURCE_LOCALIZED,
                ),
            )
        )
    if failure is not None:
        steps.append(
            (
                CausalStepKind.OBSERVED_FAILURE,
                f"{failure.category.value}: {failure.symbol or failure.message}",
                _ids(reference_by_kind, EvidenceReferenceKind.FAILURE_SYMBOL_MATCH),
            )
        )
    return tuple(
        CausalStep(index, kind, description, evidence_ids)
        for index, (kind, description, evidence_ids) in enumerate(steps, start=1)
    )


def _hypothesis_sort_key(hypothesis: RootCauseHypothesis) -> tuple[object, ...]:
    coordinate = (
        _dependency_identity(hypothesis.implicated_dependencies[0])
        if hypothesis.implicated_dependencies
        else "~"
    )
    return (
        -hypothesis.evidence_score,
        len(hypothesis.contradictory_evidence),
        len(hypothesis.missing_evidence),
        coordinate,
        hypothesis.id,
    )


def _diagnosis_status(
    hypotheses: tuple[RootCauseHypothesis, ...],
) -> DiagnosisStatus:
    statuses = {item.status for item in hypotheses}
    if HypothesisStatus.SUPPORTED in statuses:
        return DiagnosisStatus.SUPPORTED_DIAGNOSIS
    if HypothesisStatus.AMBIGUOUS in statuses:
        return DiagnosisStatus.AMBIGUOUS_DIAGNOSIS
    if HypothesisStatus.PARTIALLY_SUPPORTED in statuses:
        return DiagnosisStatus.PARTIAL_DIAGNOSIS
    return DiagnosisStatus.INSUFFICIENT_EVIDENCE


def _diagnosis_summary(
    status: DiagnosisStatus,
    hypotheses: tuple[RootCauseHypothesis, ...],
) -> str:
    if status is DiagnosisStatus.SUPPORTED_DIAGNOSIS:
        return f"Deterministic evidence supports {hypotheses[0].summary}."
    if status is DiagnosisStatus.AMBIGUOUS_DIAGNOSIS:
        return "Changed-dependency ownership is ambiguous."
    if status is DiagnosisStatus.PARTIAL_DIAGNOSIS:
        return "API evidence exists, but the causal chain is incomplete."
    return "Available local evidence does not support a causal diagnosis."


def _unresolved_questions(
    status: DiagnosisStatus,
    hypotheses: tuple[RootCauseHypothesis, ...],
    bundle: EvidenceBundle,
) -> tuple[str, ...]:
    questions: list[str] = []
    if not hypotheses:
        questions.append("Which changed dependency and API fact explain the failure?")
    if status is DiagnosisStatus.AMBIGUOUS_DIAGNOSIS:
        questions.append("Which changed dependency supplies the class at build time?")
    if any(item.missing_evidence for item in hypotheses):
        questions.append("Can the missing API, source, or dependency-path evidence be collected?")
    if any(item.contradictory_evidence for item in hypotheses):
        questions.append("What explains the failure if the relevant API remained unchanged?")
    questions.extend(bundle.issues)
    return tuple(dict.fromkeys(questions))


def _strength(score: int) -> EvidenceStrength:
    if score >= 90:
        return EvidenceStrength.VERY_STRONG
    if score >= 70:
        return EvidenceStrength.STRONG
    if score >= 50:
        return EvidenceStrength.MODERATE
    if score >= 25:
        return EvidenceStrength.WEAK
    return EvidenceStrength.INSUFFICIENT


def _evidence_inconsistencies(
    bundle: EvidenceBundle,
    attribution: DependencyAttribution,
    failure: FailureSignal | None,
    api: ApiEvidence,
) -> tuple[str, ...]:
    """Reject structural chains whose typed Phase 2-4 facts disagree."""
    issues: list[str] = []
    change = attribution.dependencies[0] if attribution.dependencies else None
    if change is None or change not in bundle.dependency_diff.changes:
        issues.append("attributed dependency change is absent from DependencyDiff")
    elif api.before != change.before or api.after != change.after:
        issues.append("API versions do not match the attributed dependency change")
    if failure and api.failure_symbol and api.failure_symbol != failure.symbol:
        issues.append("API evidence symbol does not match the primary failure symbol")
    if attribution.target_on_path:
        target = bundle.target_upgrade
        if not any(
            item.group_id == target.group_id
            and item.artifact_id == target.artifact_id
            for item in attribution.dependency_path
        ):
            issues.append("target_on_path is true but the target is absent from the path")
    if change and attribution.dependency_path:
        expected = (
            change.before
            if change.kind is DependencyChangeKind.REMOVED
            else change.after
        )
        if expected is not None and attribution.dependency_path[-1] != expected:
            issues.append("dependency path does not terminate at the attributed version")
    return tuple(issues)


def _hypothesis_id(
    kind: CausalHypothesisKind,
    attribution: DependencyAttribution,
    failure: FailureSignal | None,
) -> str:
    dependencies = "|".join(
        _dependency_change_detail(item) for item in attribution.dependencies
    )
    identity = "|".join(
        (
            kind.value,
            attribution.candidate.name,
            dependencies,
            failure.symbol if failure and failure.symbol else "",
        )
    )
    return "H-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10].upper()


def _reference(
    kind: EvidenceReferenceKind, detail: str, artifact: str
) -> EvidenceReference:
    identity = f"{kind.value}|{detail}|{artifact}"
    reference_id = "E-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10].upper()
    return EvidenceReference(reference_id, kind, detail, artifact)


def _hypothesis_summary(
    kind: CausalHypothesisKind,
    attribution: DependencyAttribution,
    api: ApiEvidence,
) -> str:
    dependency = (
        _dependency_identity(attribution.dependencies[0])
        if attribution.dependencies
        else "an unresolved dependency"
    )
    subject = api.failure_symbol or api.class_name
    templates = {
        CausalHypothesisKind.REMOVED_MEMBER: f"{dependency} removed {subject}",
        CausalHypothesisKind.CHANGED_MEMBER_SIGNATURE:
            f"{dependency} changed the signature of {subject}",
        CausalHypothesisKind.REMOVED_CLASS:
            f"{dependency} removed class {api.class_name}",
        CausalHypothesisKind.REMOVED_PACKAGE:
            f"{dependency} removed package {api.class_name}",
        CausalHypothesisKind.REMOVED_DEPENDENCY:
            f"removal of {dependency} removed class {api.class_name}",
        CausalHypothesisKind.API_INSPECTION_UNAVAILABLE:
            f"{dependency} owns {api.class_name}, but its API could not be inspected",
        CausalHypothesisKind.RELEVANT_MEMBER_UNCHANGED:
            f"a removal of {subject} from {dependency}",
    }
    return templates[kind]


def _api_change_description(api: ApiEvidence) -> str:
    symbol = api.failure_symbol or api.class_name
    if api.kind is ApiEvidenceKind.REMOVED_MEMBER:
        return f"{symbol} is present before and absent after the dependency change"
    if api.kind is ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE:
        old = "; ".join(item.declaration for item in api.old_members) or "unavailable"
        new = "; ".join(item.declaration for item in api.new_members) or "unavailable"
        return f"{symbol} changed signature from [{old}] to [{new}]"
    if api.kind is ApiEvidenceKind.REMOVED_CLASS:
        return f"class {api.class_name} is present before and absent after"
    if api.kind is ApiEvidenceKind.PACKAGE_REMOVED:
        return f"package {api.class_name} is present before and absent after"
    if api.kind is ApiEvidenceKind.DEPENDENCY_REMOVED_WITH_CLASS:
        return f"the removed dependency previously contained {api.class_name}"
    if api.kind is ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED:
        return f"{symbol} is present with the same relevant declaration before and after"
    return f"API inspection for {api.class_name} is unavailable"


def _explanation(
    status: HypothesisStatus, summary: str, target_on_path: bool
) -> str:
    if status is HypothesisStatus.SUPPORTED:
        return f"The deterministic evidence strongly supports that {summary}."
    if status is HypothesisStatus.PARTIALLY_SUPPORTED:
        suffix = (
            " Some source evidence is missing."
            if target_on_path
            else " The change is not connected to the requested target's dependency path."
        )
        return f"The deterministic evidence suggests that {summary}.{suffix}"
    if status is HypothesisStatus.CONTRADICTED:
        return f"The collected API evidence contradicts the claim that {summary}."
    if status is HypothesisStatus.AMBIGUOUS:
        return "The available evidence does not uniquely identify one dependency owner."
    return f"There is insufficient deterministic API evidence to support that {summary}."


def _matching_context(
    contexts: tuple[SourceContext, ...], failure: FailureSignal | None
) -> SourceContext | None:
    if failure is None:
        return None
    return next(
        (
            context
            for context in contexts
            if context.file == failure.file and context.focus_line == failure.line
        ),
        None,
    )


def _exact_call_site(
    context: SourceContext, failure: FailureSignal, api: ApiEvidence
) -> bool:
    symbol = failure.symbol or api.failure_symbol
    if not symbol:
        return False
    cleaned = re.sub(r"^(?:method|class|variable)\s+", "", symbol).strip()
    token = cleaned.split("(", 1)[0].rsplit(".", 1)[-1]
    if not token:
        return False
    focus = next(
        (item.text for item in context.lines if item.number == context.focus_line),
        "",
    )
    return bool(re.search(rf"\b{re.escape(token)}\b", focus))


def _target_upgrade_detail(bundle: EvidenceBundle) -> str:
    target = bundle.target_upgrade
    return (
        f"requested target {target.group_id}:{target.artifact_id} changed "
        f"from {target.old_version} to {target.new_version}"
    )


def _dependency_change_detail(change: DependencyChange) -> str:
    coordinate = change.after or change.before
    assert coordinate is not None
    identity = f"{coordinate.group_id}:{coordinate.artifact_id}"
    if change.before and change.after:
        versions = f"{change.before.version} to {change.after.version}"
    elif change.before:
        versions = f"{change.before.version} to removed"
    else:
        assert change.after is not None
        versions = f"added at {change.after.version}"
    target = " target" if change.is_target else ""
    return f"{identity} changed {versions} ({change.relationship.value}{target})"


def _dependency_identity(change: DependencyChange) -> str:
    coordinate = change.after or change.before
    assert coordinate is not None
    classifier = f":{coordinate.classifier}" if coordinate.classifier else ""
    return f"{coordinate.group_id}:{coordinate.artifact_id}{classifier}"


def _path_detail(path: tuple[DependencyCoordinate, ...]) -> str:
    return " -> ".join(
        f"{item.group_id}:{item.artifact_id}:{item.version}" for item in path
    )


def _source_location(failure: FailureSignal | None) -> str:
    if failure is None:
        return "an unresolved source location"
    location = str(failure.file) if failure.file else failure.reported_file or "unresolved"
    return f"{location}:{failure.line}" if failure.line else location


def _ids(
    indexed: dict[EvidenceReferenceKind, str],
    *kinds: EvidenceReferenceKind,
) -> tuple[str, ...]:
    return tuple(indexed[kind] for kind in kinds if kind in indexed)


def _reference_to_dict(reference: EvidenceReference) -> dict[str, object]:
    return {
        "id": reference.id,
        "kind": reference.kind.value,
        "detail": reference.detail,
        "artifact": reference.artifact,
    }


def _coordinate_to_dict(coordinate: DependencyCoordinate) -> dict[str, object]:
    return {
        "group_id": coordinate.group_id,
        "artifact_id": coordinate.artifact_id,
        "version": coordinate.version,
        "type": coordinate.type,
        "classifier": coordinate.classifier,
    }


def _change_to_dict(change: DependencyChange) -> dict[str, object]:
    return {
        "kind": change.kind.value,
        "relationship": change.relationship.value,
        "is_target": change.is_target,
        "before": _coordinate_to_dict(change.before) if change.before else None,
        "after": _coordinate_to_dict(change.after) if change.after else None,
    }


def _failure_to_dict(failure: FailureSignal | None) -> object:
    if failure is None:
        return None
    return {
        "category": failure.category.value,
        "symbol": failure.symbol,
        "file": str(failure.file) if failure.file else None,
        "line": failure.line,
        "column": failure.column,
        "message": failure.message,
    }
