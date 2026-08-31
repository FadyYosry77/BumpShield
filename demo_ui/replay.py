"""Read-only, integrity-checked presentation of recorded BumpShield runs.

Replay code lives outside the BumpShield engine.  It reads a small committed
artifact bundle, verifies every evidence hash, checks internal consistency, and
then produces the same view models used by the live Streamlit presentation.
It never invokes Git, Maven, Java, Codex, or any BumpShield execution service.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from bumpshield.models import MigrationPlanningResult, RepairResult, ReproductionResult

from demo_ui.adapters import (
    ApiChangeView,
    AttemptView,
    DiagnosisView,
    FailureView,
    InvestigationView,
    PlanView,
    UpgradeView,
    VerificationView,
    planning_to_view,
    repair_to_view,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = PROJECT_ROOT / "demo_ui" / "replay"
DEFAULT_REPLAY_BUNDLE = REPLAY_ROOT / "transitive-api-v1"
REAL_WORLD_REPLAY_BUNDLE = REPLAY_ROOT / "bonecp-real-world-v1"
REPLAY_SCENARIOS = {
    "Synthetic Transitive Demo": DEFAULT_REPLAY_BUNDLE,
    "BoneCP Real-World Showcase": REAL_WORLD_REPLAY_BUNDLE,
}
REPLAY_SCHEMA_VERSION = 1
MAX_REPLAY_ARTIFACT_BYTES = 200_000
VERIFIED_STATUS = "VERIFIED_MIGRATION"

REPLAY_STAGES = (
    "Regression",
    "Dependency Diff",
    "Failure Localization",
    "API Evidence",
    "Causal Diagnosis",
    "Migration Plan",
    "AI Repair",
    "Compile",
    "Tests",
    "Independent Verification",
)

REQUIRED_ARTIFACTS = {
    "reproduction",
    "dependency_diff",
    "failure",
    "api_evidence",
    "diagnosis",
    "migration_plan",
    "execution",
    "patch",
    "verification",
    "migration_report",
}


class ReplayBundleError(ValueError):
    """Raised when recorded evidence cannot be presented safely or honestly."""


@dataclass(frozen=True, slots=True)
class ReplayCommandView:
    """Recorded command result; no command is executed during replay."""

    command: str
    status: str


@dataclass(frozen=True, slots=True)
class ReplayTestView:
    """Recorded test totals supported by stored execution evidence."""

    command: str
    status: str
    tests: int
    failures: int
    errors: int
    skipped: int


@dataclass(frozen=True, slots=True)
class ReplayReproductionView:
    """Recorded base-pass and updated-fail regression evidence."""

    status: str
    base: ReplayTestView
    updated: ReplayCommandView
    updated_reason: str


@dataclass(frozen=True, slots=True)
class ReplayProvenanceView:
    """Portable provenance for one sanitized recorded run."""

    bundle_id: str
    source_run_type: str
    source_run_id: str
    recorded_at: str | None
    fixture: str
    source_report: str
    original_final_status: str
    sanitization_status: str
    original_repository_unchanged: bool
    toolchain: tuple[tuple[str, str], ...]
    bundle_hash: str
    project: str | None
    showcase_type: str | None
    upstream_repository: str | None


@dataclass(frozen=True, slots=True)
class ReplayBundle:
    """Validated recorded evidence ready for shared GUI rendering."""

    root: Path
    bundle_id: str
    bundle_hash: str
    artifact_hashes: tuple[tuple[str, str], ...]
    investigation: InvestigationView
    verification: VerificationView
    reproduction: ReplayReproductionView
    compile: ReplayCommandView
    tests: ReplayTestView
    provenance: ReplayProvenanceView
    patch: str
    migration_report: str
    stages: tuple[str, ...]


class RunPresentationSource(Protocol):
    """Presentation-only source shared by live and recorded views."""

    @property
    def mode_label(self) -> str:
        """Return explicit source label shown by the GUI."""

    def investigation_view(self) -> InvestigationView:
        """Return investigation screen model."""

    def verification_view(self) -> VerificationView | None:
        """Return verifier-controlled result when available."""


@dataclass(frozen=True, slots=True)
class LiveRunSource:
    """Adapt already-produced live results without changing live execution."""

    planning: MigrationPlanningResult
    reproduction: ReproductionResult | None = None
    repair: RepairResult | None = None

    @property
    def mode_label(self) -> str:
        return "LIVE RUN"

    def investigation_view(self) -> InvestigationView:
        return planning_to_view(self.planning, self.reproduction)

    def verification_view(self) -> VerificationView | None:
        return repair_to_view(self.repair) if self.repair is not None else None


@dataclass(frozen=True, slots=True)
class RecordedRunSource:
    """Validated offline source for recorded presentation."""

    bundle: ReplayBundle

    @classmethod
    def load(
        cls,
        bundle_directory: Path = DEFAULT_REPLAY_BUNDLE,
        *,
        allowed_root: Path = REPLAY_ROOT,
    ) -> "RecordedRunSource":
        return cls(ReplayBundleValidator(allowed_root=allowed_root).validate(bundle_directory))

    @property
    def mode_label(self) -> str:
        if self.bundle.provenance.source_run_type == "REAL_OPEN_SOURCE_PROJECT":
            return "RECORDED REAL-WORLD VERIFIED RUN"
        return "RECORDED VERIFIED RUN"

    def investigation_view(self) -> InvestigationView:
        return self.bundle.investigation

    def verification_view(self) -> VerificationView:
        return self.bundle.verification


class ReplayBundleValidator:
    """Validate portable replay evidence without invoking external tools."""

    def __init__(
        self,
        *,
        allowed_root: Path = REPLAY_ROOT,
        max_artifact_bytes: int = MAX_REPLAY_ARTIFACT_BYTES,
    ) -> None:
        if max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        self.allowed_root = Path(allowed_root)
        self.max_artifact_bytes = max_artifact_bytes

    def validate(self, bundle_directory: Path) -> ReplayBundle:
        root = self._safe_bundle_root(bundle_directory)
        manifest_path = self._safe_file(root, Path("manifest.json"))
        provenance_path = self._safe_file(root, Path("provenance.json"))
        manifest = self._json_file(manifest_path)
        provenance = self._json_file(provenance_path)

        if manifest.get("replay_schema_version") != REPLAY_SCHEMA_VERSION:
            raise ReplayBundleError("Unsupported replay schema version")
        bundle_id = _required_text(manifest, "replay_bundle_id")
        if provenance.get("replay_bundle_id") != bundle_id:
            raise ReplayBundleError("Replay bundle identity is inconsistent")
        stages = tuple(manifest.get("stage_order", ()))
        if stages != REPLAY_STAGES:
            raise ReplayBundleError("Replay stage order is invalid")

        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != REQUIRED_ARTIFACTS:
            raise ReplayBundleError("Replay manifest has invalid artifact set")
        paths = {
            key: self._safe_file(root, _portable_relative_path(value))
            for key, value in artifacts.items()
        }
        expected_hashes = provenance.get("artifact_hashes")
        if not isinstance(expected_hashes, dict):
            raise ReplayBundleError("Replay provenance lacks artifact hashes")
        hashed_paths = {"manifest.json": manifest_path, **{
            path.name: path for path in paths.values()
        }}
        if set(expected_hashes) != set(hashed_paths):
            raise ReplayBundleError("Replay provenance hash set is incomplete")
        observed_hashes = {
            name: _sha256_file(path, self.max_artifact_bytes)
            for name, path in sorted(hashed_paths.items())
        }
        if observed_hashes != expected_hashes:
            raise ReplayBundleError("Replay artifact hash mismatch")
        bundle_hash = _bundle_hash(observed_hashes)
        if provenance.get("bundle_hash") != bundle_hash:
            raise ReplayBundleError("Replay bundle hash mismatch")

        data = {
            key: (
                self._text_file(path)
                if key in {"patch", "migration_report"}
                else self._json_file(path)
            )
            for key, path in paths.items()
        }
        return self._build_bundle(
            root,
            bundle_id,
            bundle_hash,
            observed_hashes,
            provenance,
            data,
            stages,
        )

    def _safe_bundle_root(self, bundle_directory: Path) -> Path:
        allowed = self.allowed_root.resolve()
        requested = Path(bundle_directory)
        candidate = requested if requested.is_absolute() else allowed / requested
        if candidate.is_symlink():
            raise ReplayBundleError("Replay bundle cannot be a symlink")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(allowed)
        except ValueError as error:
            raise ReplayBundleError("Replay bundle escapes allowlisted root") from error
        if not resolved.is_dir():
            raise ReplayBundleError("Replay bundle directory is missing")
        return resolved

    def _safe_file(self, root: Path, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise ReplayBundleError("Replay artifact path is not portable")
        candidate = root / relative
        if candidate.is_symlink():
            raise ReplayBundleError("Replay artifact cannot be a symlink")
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ReplayBundleError("Replay artifact escapes bundle root") from error
        if not resolved.is_file():
            raise ReplayBundleError(f"Required replay artifact is missing: {relative}")
        if resolved.stat().st_size > self.max_artifact_bytes:
            raise ReplayBundleError(f"Replay artifact exceeds size limit: {relative}")
        return resolved

    def _json_file(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(self._text_file(path))
        except json.JSONDecodeError as error:
            raise ReplayBundleError(f"Replay JSON is invalid: {path.name}") from error
        if not isinstance(value, dict):
            raise ReplayBundleError(f"Replay JSON must be an object: {path.name}")
        return value

    def _text_file(self, path: Path) -> str:
        raw = path.read_bytes()
        if len(raw) > self.max_artifact_bytes:
            raise ReplayBundleError(f"Replay artifact exceeds size limit: {path.name}")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReplayBundleError(f"Replay artifact is not UTF-8: {path.name}") from error

    def _build_bundle(
        self,
        root: Path,
        bundle_id: str,
        bundle_hash: str,
        artifact_hashes: Mapping[str, str],
        provenance: Mapping[str, Any],
        data: Mapping[str, Any],
        stages: tuple[str, ...],
    ) -> ReplayBundle:
        reproduction = _mapping(data["reproduction"], "reproduction")
        dependency = _mapping(data["dependency_diff"], "dependency diff")
        failure = _mapping(data["failure"], "failure")
        api = _mapping(data["api_evidence"], "API evidence")
        diagnosis = _mapping(data["diagnosis"], "diagnosis")
        plan = _mapping(data["migration_plan"], "migration plan")
        execution = _mapping(data["execution"], "execution")
        verification = _mapping(data["verification"], "verification")
        patch = str(data["patch"])
        report = str(data["migration_report"])

        requested = _upgrade_from_target(_mapping(dependency.get("target"), "target"))
        causal_change = _find_causal_change(dependency)
        causal = _upgrade_from_change(causal_change)
        _require_consistency(requested, causal, failure, api, diagnosis, plan, provenance)

        verified = _verification_is_verified(verification)
        if not verified:
            raise ReplayBundleError("Recorded independent verification is not verified")
        if not patch.startswith("diff --git "):
            raise ReplayBundleError("Recorded Git patch is missing or invalid")
        files_changed, lines_added, lines_removed = _patch_stats(patch)

        reproduction_view = _reproduction_view(reproduction)
        compile_view, tests_view = _execution_views(execution)
        failure_view = _failure_view(failure)
        api_view = _api_view(api, plan)
        diagnosis_view = _diagnosis_view(diagnosis)
        plan_view = _plan_view(plan)
        investigation = InvestigationView(
            run_id=_required_text(diagnosis, "run_id"),
            artifact_directory=root,
            requested=requested,
            causal=causal,
            dependency_path=_dependency_path(requested, causal),
            failure=failure_view,
            api_change=api_view,
            diagnosis=diagnosis_view,
            plan=plan_view,
            regression_confirmed=reproduction_view.status == "CONFIRMED",
            dependency_analysis_complete=True,
        )
        checks = tuple(
            (
                _required_text(_mapping(item, "verification check"), "name"),
                _required_text(_mapping(item, "verification check"), "status"),
                _required_text(_mapping(item, "verification check"), "details"),
            )
            for item in _list(verification.get("checks"), "verification checks")
        )
        attempt = AttemptView(
            number=int(provenance.get("attempt_count", 1)),
            status="VERIFIED",
            provider_status="SUCCESS",
            files_changed=files_changed,
            lines_added=lines_added,
            lines_removed=lines_removed,
            compile_status=compile_view.status,
            test_status=tests_view.status,
            verification_status=VERIFIED_STATUS,
            representative_failure=None,
            provider_issue=None,
            patch=patch,
        )
        verification_view = VerificationView(
            final_status=VERIFIED_STATUS,
            verified=True,
            checks=checks,
            reasons=tuple(str(item) for item in verification.get("reasons", ())),
            attempts=(attempt,),
            winning_attempt=attempt.number,
            artifact_directory=root,
        )
        provenance_view = ReplayProvenanceView(
            bundle_id=bundle_id,
            source_run_type=_required_text(provenance, "source_run_type"),
            source_run_id=_required_text(provenance, "source_run_id"),
            recorded_at=(str(provenance["recorded_at"]) if provenance.get("recorded_at") else None),
            fixture=_required_text(provenance, "fixture"),
            source_report=_required_text(provenance, "source_report"),
            original_final_status=_required_text(provenance, "original_final_status"),
            sanitization_status=_required_text(provenance, "sanitization_status"),
            original_repository_unchanged=(
                provenance.get("original_repository_unchanged") is True
            ),
            toolchain=tuple(
                (str(key), str(value))
                for key, value in sorted(_mapping(provenance.get("toolchain"), "toolchain").items())
            ),
            bundle_hash=bundle_hash,
            project=(str(provenance["project"]) if provenance.get("project") else None),
            showcase_type=(
                str(provenance["showcase_type"])
                if provenance.get("showcase_type")
                else None
            ),
            upstream_repository=(
                str(provenance["upstream_repository"])
                if provenance.get("upstream_repository")
                else None
            ),
        )
        return ReplayBundle(
            root=root,
            bundle_id=bundle_id,
            bundle_hash=bundle_hash,
            artifact_hashes=tuple(sorted(artifact_hashes.items())),
            investigation=investigation,
            verification=verification_view,
            reproduction=reproduction_view,
            compile=compile_view,
            tests=tests_view,
            provenance=provenance_view,
            patch=patch,
            migration_report=report,
            stages=stages,
        )


def _portable_relative_path(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise ReplayBundleError("Replay artifact path must be non-empty text")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ReplayBundleError("Replay artifact path is not portable")
    return path


def _sha256_file(path: Path, max_bytes: int) -> str:
    if path.stat().st_size > max_bytes:
        raise ReplayBundleError(f"Replay artifact exceeds size limit: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_hash(hashes: Mapping[str, str]) -> str:
    canonical = json.dumps(
        dict(sorted(hashes.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReplayBundleError(f"Recorded {label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReplayBundleError(f"Recorded {label} must be a list")
    return value


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReplayBundleError(f"Recorded field is missing: {key}")
    return value


def _upgrade_from_target(target: Mapping[str, Any]) -> UpgradeView:
    return UpgradeView(
        group_id=_required_text(target, "group_id"),
        artifact_id=_required_text(target, "artifact_id"),
        old_version=_required_text(target, "resolved_base_version"),
        new_version=_required_text(target, "resolved_updated_version"),
        relationship="DIRECT",
    )


def _find_causal_change(dependency: Mapping[str, Any]) -> dict[str, Any]:
    for value in _list(dependency.get("changes"), "dependency changes"):
        change = _mapping(value, "dependency change")
        if change.get("relationship") == "TRANSITIVE" and change.get("kind") == "UPDATED":
            return change
    for value in _list(dependency.get("changes"), "dependency changes"):
        change = _mapping(value, "dependency change")
        if change.get("relationship") == "DIRECT" and change.get("is_target") is True:
            return change
    raise ReplayBundleError("Recorded causal dependency is missing")


def _upgrade_from_change(change: Mapping[str, Any]) -> UpgradeView:
    before = _mapping(change.get("before"), "causal dependency before")
    after = _mapping(change.get("after"), "causal dependency after")
    if (before.get("group_id"), before.get("artifact_id")) != (
        after.get("group_id"), after.get("artifact_id")
    ):
        raise ReplayBundleError("Recorded causal dependency identity changed")
    return UpgradeView(
        group_id=_required_text(after, "group_id"),
        artifact_id=_required_text(after, "artifact_id"),
        old_version=_required_text(before, "version"),
        new_version=_required_text(after, "version"),
        relationship=_required_text(change, "relationship"),
    )


def _dependency_path(requested: UpgradeView, causal: UpgradeView) -> tuple[str, ...]:
    requested_coordinate = (
        f"{requested.group_id}:{requested.artifact_id}:{requested.new_version}"
    )
    causal_coordinate = f"{causal.group_id}:{causal.artifact_id}:{causal.new_version}"
    if requested_coordinate == causal_coordinate:
        return (requested_coordinate,)
    return (requested_coordinate, causal_coordinate)


def _require_consistency(
    requested: UpgradeView,
    causal: UpgradeView,
    failure: Mapping[str, Any],
    api: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
    plan: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> None:
    target = _mapping(plan.get("target_upgrade"), "plan target")
    target_tuple = (
        _required_text(target, "group_id"),
        _required_text(target, "artifact_id"),
        _required_text(target, "old_version"),
        _required_text(target, "new_version"),
    )
    if target_tuple != (
        requested.group_id,
        requested.artifact_id,
        requested.old_version,
        requested.new_version,
    ):
        raise ReplayBundleError("Recorded target dependency is inconsistent")
    affected = _mapping(plan.get("affected_dependency"), "affected dependency")
    affected_before = _mapping(affected.get("before"), "affected dependency before")
    affected_after = _mapping(affected.get("after"), "affected dependency after")
    if (
        affected_after.get("group_id"),
        affected_after.get("artifact_id"),
        affected_before.get("version"),
        affected_after.get("version"),
    ) != (causal.group_id, causal.artifact_id, causal.old_version, causal.new_version):
        raise ReplayBundleError("Recorded causal dependency is inconsistent")
    symbol = _required_text(failure, "symbol")
    if symbol != api.get("failure_symbol") or symbol != plan.get("affected_member"):
        raise ReplayBundleError("Recorded failing API is inconsistent")
    if diagnosis.get("status") != "SUPPORTED_DIAGNOSIS":
        raise ReplayBundleError("Recorded diagnosis is not supported")
    if plan.get("status") != "PLAN_READY":
        raise ReplayBundleError("Recorded migration plan is not ready")
    if provenance.get("original_final_status") != VERIFIED_STATUS:
        raise ReplayBundleError("Replay provenance does not record verified migration")
    provenance_target = _mapping(provenance.get("target_dependency"), "provenance target")
    provenance_causal = _mapping(provenance.get("causal_dependency"), "provenance causal")
    if provenance_target.get("artifact_id") != requested.artifact_id:
        raise ReplayBundleError("Replay target provenance is inconsistent")
    if provenance_causal.get("artifact_id") != causal.artifact_id:
        raise ReplayBundleError("Replay causal provenance is inconsistent")


def _verification_is_verified(verification: Mapping[str, Any]) -> bool:
    mandatory = (
        "target_dependency_retained",
        "causal_dependency_retained",
        "compilation_passed",
        "tests_passed",
        "tests_preserved",
        "tests_enabled",
        "test_execution_not_skipped",
        "patch_scope_acceptable",
    )
    checks = verification.get("checks")
    return bool(
        verification.get("status") == VERIFIED_STATUS
        and all(verification.get(key) is True for key in mandatory)
        and isinstance(checks, list)
        and checks
        and all(isinstance(item, dict) and item.get("status") == "PASS" for item in checks)
    )


def _patch_stats(patch: str) -> tuple[int, int, int]:
    lines = patch.splitlines()
    files = sum(line.startswith("diff --git ") for line in lines)
    added = sum(line.startswith("+") and not line.startswith("+++") for line in lines)
    removed = sum(line.startswith("-") and not line.startswith("---") for line in lines)
    if files < 1:
        raise ReplayBundleError("Recorded patch has no changed files")
    return files, added, removed


def _reproduction_view(data: Mapping[str, Any]) -> ReplayReproductionView:
    base = _mapping(data.get("base"), "base reproduction")
    updated = _mapping(data.get("updated"), "updated reproduction")
    base_tests = _mapping(base.get("tests"), "base tests")
    return ReplayReproductionView(
        status=_required_text(data, "status"),
        base=ReplayTestView(
            command=_required_text(base, "command"),
            status=_required_text(base, "status"),
            tests=int(base_tests.get("tests", 0)),
            failures=int(base_tests.get("failures", 0)),
            errors=int(base_tests.get("errors", 0)),
            skipped=int(base_tests.get("skipped", 0)),
        ),
        updated=ReplayCommandView(
            command=_required_text(updated, "command"),
            status=_required_text(updated, "status"),
        ),
        updated_reason=_required_text(updated, "reason"),
    )


def _execution_views(data: Mapping[str, Any]) -> tuple[ReplayCommandView, ReplayTestView]:
    compile_data = _mapping(data.get("compile"), "compile execution")
    tests = _mapping(data.get("tests"), "test execution")
    return (
        ReplayCommandView(
            command=_required_text(compile_data, "command"),
            status=_required_text(compile_data, "status"),
        ),
        ReplayTestView(
            command=_required_text(tests, "command"),
            status=_required_text(tests, "status"),
            tests=int(tests.get("tests", 0)),
            failures=int(tests.get("failures", 0)),
            errors=int(tests.get("errors", 0)),
            skipped=int(tests.get("skipped", 0)),
        ),
    )


def _failure_view(data: Mapping[str, Any]) -> FailureView:
    lines = _list(data.get("source_context"), "source context")
    focus = int(data.get("line", 0))
    excerpt = "\n".join(
        f"{'>' if int(_mapping(item, 'source line').get('number', 0)) == focus else ' '} "
        f"{int(_mapping(item, 'source line').get('number', 0)):4} | "
        f"{str(_mapping(item, 'source line').get('text', ''))}"
        for item in lines
    )
    return FailureView(
        category=_required_text(data, "category"),
        file=_required_text(data, "file"),
        line=focus,
        symbol=_required_text(data, "symbol"),
        message=_required_text(data, "message"),
        source_excerpt=excerpt,
    )


def _api_view(api: Mapping[str, Any], plan: Mapping[str, Any]) -> ApiChangeView:
    old_members = tuple(
        _required_text(_mapping(item, "old API member"), "declaration")
        for item in _list(api.get("old_members"), "old API members")
    )
    new_members = tuple(
        _required_text(_mapping(item, "new API member"), "declaration")
        for item in _list(api.get("new_class_members"), "new class members")
        if _mapping(item, "new API member").get("kind") == "METHOD"
    )
    candidates = tuple(
        _required_text(_mapping(item, "migration candidate"), "declaration")
        for item in _list(plan.get("new_api_candidates"), "migration candidates")
    )
    before = _mapping(api.get("before"), "old API dependency")
    after = _mapping(api.get("after"), "new API dependency")
    return ApiChangeView(
        kind=_required_text(api, "kind"),
        class_name=_required_text(api, "class"),
        old_version=_required_text(before, "version"),
        new_version=_required_text(after, "version"),
        old_members=old_members,
        new_members=new_members,
        old_class_present=api.get("old_class_present") is True,
        new_class_present=api.get("new_class_present") is True,
        candidates=candidates,
    )


def _diagnosis_view(data: Mapping[str, Any]) -> DiagnosisView:
    chain = tuple(
        _required_text(_mapping(item, "causal step"), "description")
        for item in _list(data.get("causal_chain"), "causal chain")
    )
    return DiagnosisView(
        status=_required_text(data, "status"),
        summary=_required_text(data, "summary"),
        evidence_strength=_required_text(data, "evidence_strength"),
        evidence_score=int(data.get("evidence_score", 0)),
        causal_steps=chain,
        explanation=_required_text(data, "explanation"),
    )


def _plan_view(data: Mapping[str, Any]) -> PlanView:
    candidates = tuple(
        _required_text(_mapping(item, "migration candidate"), "declaration")
        for item in _list(data.get("new_api_candidates"), "migration candidates")
    )
    locations = _list(data.get("affected_source_locations"), "affected source locations")
    return PlanView(
        status=_required_text(data, "status"),
        migration_kind=_required_text(data, "migration_kind"),
        affected_api=_required_text(data, "affected_member"),
        candidates=candidates,
        affected_files=tuple(
            _required_text(_mapping(item, "affected source location"), "file")
            for item in locations
        ),
        allowed_files=tuple(str(item) for item in _list(data.get("allowed_files"), "allowed files")),
        constraints=tuple(str(item) for item in _list(data.get("constraints"), "constraints")),
        verification_requirements=tuple(
            str(item)
            for item in _list(data.get("verification_requirements"), "verification requirements")
        ),
        scope=_required_text(data, "scope"),
        required_outcome=_required_text(data, "required_outcome"),
        cautious_repair=data.get("cautious_repair") is True,
    )
