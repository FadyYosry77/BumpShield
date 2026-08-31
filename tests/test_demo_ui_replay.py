from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from demo_ui.adapters import InvestigationView, VerificationView
from demo_ui.replay import (
    DEFAULT_REPLAY_BUNDLE,
    PROJECT_ROOT,
    REAL_WORLD_REPLAY_BUNDLE,
    REPLAY_SCHEMA_VERSION,
    LiveRunSource,
    RecordedRunSource,
    ReplayBundleError,
    ReplayBundleValidator,
)
from demo_ui.state import initialize_state, reset_replay_state


def _copy_bundle(tmp_path: Path) -> Path:
    destination = tmp_path / "bundle"
    shutil.copytree(DEFAULT_REPLAY_BUNDLE, destination)
    return destination


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rehash(bundle: Path) -> None:
    manifest = _read_json(bundle / "manifest.json")
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, dict)
    names = {"manifest.json", *(str(item) for item in artifacts.values())}
    hashes = {
        name: hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        for name in sorted(names)
    }
    canonical = json.dumps(
        hashes,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    provenance = _read_json(bundle / "provenance.json")
    provenance["artifact_hashes"] = hashes
    provenance["bundle_hash"] = hashlib.sha256(canonical).hexdigest()
    _write_json(bundle / "provenance.json", provenance)


def test_recorded_bundle_is_valid_and_verifier_controls_success() -> None:
    source = RecordedRunSource.load()

    assert source.mode_label == "RECORDED VERIFIED RUN"
    assert isinstance(source.investigation_view(), InvestigationView)
    assert isinstance(source.verification_view(), VerificationView)
    assert source.verification_view().verified is True
    assert source.verification_view().final_status == "VERIFIED_MIGRATION"
    assert source.bundle.investigation.requested.artifact_id == "c011-core"
    assert source.bundle.investigation.causal is not None
    assert source.bundle.investigation.causal.artifact_id == "c011-legacy-api"


def test_recorded_bundle_hashes_every_evidence_file() -> None:
    bundle = RecordedRunSource.load().bundle

    hashed = dict(bundle.artifact_hashes)
    assert "manifest.json" in hashed
    assert "patch.diff" in hashed
    assert "verification.json" in hashed
    assert len(hashed) == 11
    assert len(bundle.bundle_hash) == 64


def test_real_world_bonecp_bundle_is_verified_direct_and_portable() -> None:
    source = RecordedRunSource.load(REAL_WORLD_REPLAY_BUNDLE)

    assert source.mode_label == "RECORDED REAL-WORLD VERIFIED RUN"
    assert source.verification_view().final_status == "VERIFIED_MIGRATION"
    assert source.bundle.investigation.requested.artifact_id == "guava"
    assert source.bundle.investigation.causal.relationship == "DIRECT"
    assert source.bundle.investigation.dependency_path == (
        "com.google.guava:guava:21.0",
    )
    assert source.bundle.tests.tests == 197
    assert source.bundle.provenance.project == "BoneCP"
    for path in REAL_WORLD_REPLAY_BUNDLE.iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "/home/hp/" not in text
            assert "/tmp/" not in text


def test_real_world_replay_loads_without_external_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("external execution attempted")

    monkeypatch.setattr("subprocess.run", forbidden)
    source = RecordedRunSource.load(REAL_WORLD_REPLAY_BUNDLE)

    assert source.verification_view().verified is True


def test_real_world_showcase_lock_hashes_all_result_files() -> None:
    root = PROJECT_ROOT / "showcase" / "real-world"
    lock = _read_json(root / "showcase-lock.json")
    expected = lock["result_file_hashes"]
    assert isinstance(expected, dict)
    observed = {
        str(path): hashlib.sha256((root / str(path)).read_bytes()).hexdigest()
        for path in expected
    }

    assert observed == expected
    assert lock["final_result"] == "VERIFIED_MIGRATION"
    assert lock["benchmark_membership"] == "NOT_PART_OF_BUMP_FINAL_V1"


def test_tampered_patch_is_rejected(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    with (bundle / "patch.diff").open("a", encoding="utf-8") as handle:
        handle.write("\n# tampered\n")

    with pytest.raises(ReplayBundleError, match="hash mismatch"):
        ReplayBundleValidator(allowed_root=tmp_path).validate(bundle)


def test_missing_artifact_is_rejected(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    (bundle / "verification.json").unlink()

    with pytest.raises(ReplayBundleError, match="missing"):
        ReplayBundleValidator(allowed_root=tmp_path).validate(bundle)


def test_wrong_schema_version_is_rejected(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    manifest = _read_json(bundle / "manifest.json")
    manifest["replay_schema_version"] = REPLAY_SCHEMA_VERSION + 1
    _write_json(bundle / "manifest.json", manifest)

    with pytest.raises(ReplayBundleError, match="schema"):
        ReplayBundleValidator(allowed_root=tmp_path).validate(bundle)


@pytest.mark.parametrize("path", ["../outside.json", "/tmp/outside.json"])
def test_manifest_path_escape_is_rejected(tmp_path: Path, path: str) -> None:
    bundle = _copy_bundle(tmp_path)
    manifest = _read_json(bundle / "manifest.json")
    artifacts = manifest["artifacts"]
    assert isinstance(artifacts, dict)
    artifacts["verification"] = path
    _write_json(bundle / "manifest.json", manifest)

    with pytest.raises(ReplayBundleError, match="portable"):
        ReplayBundleValidator(allowed_root=tmp_path).validate(bundle)


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    outside = tmp_path / "outside.diff"
    outside.write_text("diff --git fake\n", encoding="utf-8")
    (bundle / "patch.diff").unlink()
    (bundle / "patch.diff").symlink_to(outside)

    with pytest.raises(ReplayBundleError, match="symlink"):
        ReplayBundleValidator(allowed_root=tmp_path).validate(bundle)


def test_nonverified_independent_verification_is_rejected(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    verification = _read_json(bundle / "verification.json")
    verification["status"] = "VERIFICATION_FAILED"
    _write_json(bundle / "verification.json", verification)
    _rehash(bundle)

    with pytest.raises(ReplayBundleError, match="not verified"):
        ReplayBundleValidator(allowed_root=tmp_path).validate(bundle)


def test_empty_verification_checks_are_rejected(tmp_path: Path) -> None:
    bundle = _copy_bundle(tmp_path)
    verification = _read_json(bundle / "verification.json")
    verification["checks"] = []
    _write_json(bundle / "verification.json", verification)
    _rehash(bundle)

    with pytest.raises(ReplayBundleError, match="not verified"):
        ReplayBundleValidator(allowed_root=tmp_path).validate(bundle)


def test_bundle_is_portable_and_sanitization_is_declared() -> None:
    source = RecordedRunSource.load()
    root = source.bundle.root

    for path in root.iterdir():
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "/home/hp/" not in text
            assert "/tmp/" not in text
    assert "Portable presentation copy" in source.bundle.provenance.sanitization_status
    assert source.bundle.provenance.source_run_type == "REAL_VERIFIED_BENCHMARK_TRIAL"


def test_replay_loads_with_external_execution_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("external execution attempted")

    monkeypatch.setattr("subprocess.run", forbidden)
    before = {
        path.relative_to(DEFAULT_REPLAY_BUNDLE): (path.stat().st_mtime_ns, path.read_bytes())
        for path in DEFAULT_REPLAY_BUNDLE.iterdir()
        if path.is_file()
    }

    source = RecordedRunSource.load()

    after = {
        path.relative_to(DEFAULT_REPLAY_BUNDLE): (path.stat().st_mtime_ns, path.read_bytes())
        for path in DEFAULT_REPLAY_BUNDLE.iterdir()
        if path.is_file()
    }
    assert source.verification_view().verified is True
    assert before == after


def test_live_and_recorded_sources_share_screen_model_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded = RecordedRunSource.load()
    investigation = recorded.investigation_view()
    verification = recorded.verification_view()
    monkeypatch.setattr("demo_ui.replay.planning_to_view", lambda *_: investigation)
    monkeypatch.setattr("demo_ui.replay.repair_to_view", lambda *_: verification)
    live = LiveRunSource(object(), object(), object())  # type: ignore[arg-type]

    assert type(live.investigation_view()) is type(recorded.investigation_view())
    assert type(live.verification_view()) is type(recorded.verification_view())


def test_session_defaults_to_recorded_mode_and_restart_is_read_only() -> None:
    state: dict[str, object] = {}
    initialize_state(state)

    assert state["demo_mode"] == "Recorded Verified Run"
    assert state["replay_scenario"] == "Synthetic Transitive Demo"
    state["replay_started"] = True
    state["replay_step"] = 9
    state["replay_show_all"] = True
    reset_replay_state(state)

    assert state["replay_started"] is False
    assert state["replay_step"] == 0
    assert state["replay_show_all"] is False
