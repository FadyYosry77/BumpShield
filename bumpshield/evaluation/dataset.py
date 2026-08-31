"""Deterministic final-dataset validation, locking, and drift detection."""

from __future__ import annotations

import json
from typing import Protocol
from dataclasses import dataclass
from pathlib import Path

from bumpshield.evaluation.freeze import load_frozen_config, stable_digest
from bumpshield.evaluation.loader import load_benchmark_suite
from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseType,
    BenchmarkSuite,
    BenchmarkValidation,
    BenchmarkValidationStatus,
    DatasetSplit,
)
from bumpshield.evaluation.serialization import jsonable


class DatasetFreezeError(ValueError):
    """Raised when final dataset validation or lock integrity fails."""


class CaseValidation(Protocol):
    def validate(self, case: BenchmarkCase) -> BenchmarkValidation:
        """Return deterministic base/updated and target-resolution evidence."""
        ...


@dataclass(frozen=True, slots=True)
class DatasetCaseValidation:
    """One deterministic case-validation record."""

    case_id: str
    status: BenchmarkValidationStatus
    reason: str | None
    reproduction_status: str | None
    target_versions_matched: bool | None
    relationship_valid: bool
    split_valid: bool
    provenance_present: bool


@dataclass(frozen=True, slots=True)
class DatasetValidationResult:
    """Validation evidence collected without any repair-provider call."""

    suite_id: str
    cases: tuple[DatasetCaseValidation, ...]

    @property
    def valid(self) -> bool:
        return bool(self.cases) and all(
            item.status is BenchmarkValidationStatus.VALID
            and item.relationship_valid
            and item.split_valid
            and item.provenance_present
            for item in self.cases
        )


@dataclass(frozen=True, slots=True)
class DatasetLockResult:
    """Stable lock identity returned after creation or verification."""

    suite_id: str
    dataset_hash: str
    config_hash: str
    case_count: int
    direct_count: int
    transitive_count: int


class FinalDatasetService:
    """Validate and freeze benchmark manifests without invoking repair providers."""

    def __init__(self, validator: CaseValidation) -> None:
        self.validator = validator

    def validate(self, suite: BenchmarkSuite) -> DatasetValidationResult:
        records: list[DatasetCaseValidation] = []
        for case in suite.cases:
            observed = self.validator.validate(case)
            relationship_valid = _relationship_valid(case)
            split_valid = case.split is DatasetSplit.FINAL
            provenance_present = case.provenance is not None
            reason = observed.reason
            if observed.status is BenchmarkValidationStatus.VALID:
                defects = []
                if not relationship_valid:
                    defects.append("ground-truth dependency contradicts case type")
                if not split_valid:
                    defects.append("case split is not FINAL")
                if not provenance_present:
                    defects.append("case provenance is missing")
                reason = "; ".join(defects) or None
            records.append(
                DatasetCaseValidation(
                    case.id,
                    observed.status,
                    reason,
                    observed.reproduction_status,
                    observed.target_versions_matched,
                    relationship_valid,
                    split_valid,
                    provenance_present,
                )
            )
        return DatasetValidationResult(suite.id, tuple(records))


def write_dataset_lock(
    suite_path: Path,
    lock_path: Path,
    validation: DatasetValidationResult,
) -> DatasetLockResult:
    """Write canonical lock only after every final case validates."""
    suite = load_benchmark_suite(suite_path)
    if not validation.valid or validation.suite_id != suite.id:
        raise DatasetFreezeError("all suite cases must validate before dataset freeze")
    if suite.evaluation_config_path is None:
        raise DatasetFreezeError("final suite must reference frozen evaluation config")
    frozen = load_frozen_config(suite.evaluation_config_path)
    case_records = _case_records(suite)
    composition = _composition(suite)
    _require_final_composition(suite, composition)
    dataset_payload = {
        "suite_id": suite.id,
        "config_hash": frozen.sha256,
        "case_records": case_records,
        "composition": composition,
    }
    dataset_hash = stable_digest(dataset_payload)
    lock = {
        "schema_version": 1,
        **dataset_payload,
        "dataset_hash": dataset_hash,
        "validation": jsonable(validation),
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return DatasetLockResult(
        suite.id,
        dataset_hash,
        frozen.sha256,
        len(suite.cases),
        composition["direct"],
        composition["transitive"],
    )


def verify_dataset_lock(suite: BenchmarkSuite) -> DatasetLockResult:
    """Reject manifest, composition, commit, or frozen-config drift."""
    if suite.dataset_lock_path is None or suite.evaluation_config_path is None:
        raise DatasetFreezeError("final suite must reference config and dataset lock")
    try:
        lock = json.loads(suite.dataset_lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetFreezeError(f"could not load dataset lock: {error}") from error
    frozen = load_frozen_config(suite.evaluation_config_path)
    case_records = _case_records(suite)
    composition = _composition(suite)
    _require_final_composition(suite, composition)
    payload = {
        "suite_id": suite.id,
        "config_hash": frozen.sha256,
        "case_records": case_records,
        "composition": composition,
    }
    observed = stable_digest(payload)
    if lock.get("dataset_hash") != observed:
        raise DatasetFreezeError("dataset hash differs from frozen lock")
    if lock.get("config_hash") != frozen.sha256:
        raise DatasetFreezeError("dataset lock references different config hash")
    if lock.get("case_records") != case_records:
        raise DatasetFreezeError("case manifest hashes or commits differ from lock")
    if lock.get("composition") != composition:
        raise DatasetFreezeError("dataset composition differs from lock")
    validation = lock.get("validation", {})
    if validation.get("suite_id") != suite.id or not validation.get("cases"):
        raise DatasetFreezeError("dataset lock lacks validation evidence")
    for item in validation["cases"]:
        if (
            item.get("status") != BenchmarkValidationStatus.VALID.value
            or not item.get("relationship_valid")
            or not item.get("split_valid")
            or not item.get("provenance_present")
        ):
            raise DatasetFreezeError("dataset lock contains invalid case evidence")
    return DatasetLockResult(
        suite.id,
        observed,
        frozen.sha256,
        len(suite.cases),
        composition["direct"],
        composition["transitive"],
    )


def persist_validation(path: Path, result: DatasetValidationResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(jsonable(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _case_records(suite: BenchmarkSuite) -> list[dict[str, object]]:
    if suite.manifest_path is None:
        raise DatasetFreezeError("suite manifest path is unavailable")
    suite_data = json.loads(suite.manifest_path.read_text(encoding="utf-8"))
    paths = suite_data.get("cases")
    if not isinstance(paths, list) or len(paths) != len(suite.cases):
        raise DatasetFreezeError("suite case references are invalid")
    records: list[dict[str, object]] = []
    for case, relative in zip(suite.cases, paths, strict=True):
        path = (suite.manifest_path.parent / relative).resolve()
        raw = json.loads(path.read_text(encoding="utf-8"))
        manifest_hash = stable_digest(raw)
        records.append(
            {
                "id": case.id,
                "manifest": relative,
                "manifest_hash": manifest_hash,
                "repository": raw["task"]["repository"],
                "base_commit": case.task.base_commit,
                "updated_commit": case.task.updated_commit,
                "case_type": case.case_type.value,
                "source": case.source.value,
                "failure_kind": (
                    case.ground_truth.failure_kind.value
                    if case.ground_truth is not None
                    else None
                ),
            }
        )
    return records


def _composition(suite: BenchmarkSuite) -> dict[str, object]:
    failure_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for case in suite.cases:
        failure = (
            case.ground_truth.failure_kind.value if case.ground_truth else "UNLABELED"
        )
        failure_counts[failure] = failure_counts.get(failure, 0) + 1
        source_counts[case.source.value] = source_counts.get(case.source.value, 0) + 1
    return {
        "total": len(suite.cases),
        "direct": sum(case.case_type is BenchmarkCaseType.DIRECT for case in suite.cases),
        "transitive": sum(
            case.case_type is BenchmarkCaseType.TRANSITIVE for case in suite.cases
        ),
        "sources": dict(sorted(source_counts.items())),
        "failure_kinds": dict(sorted(failure_counts.items())),
    }


def _require_final_composition(
    suite: BenchmarkSuite, composition: dict[str, object]
) -> None:
    if suite.id != "BUMP-FINAL-v1":
        raise DatasetFreezeError("final suite ID must be BUMP-FINAL-v1")
    if composition["total"] != 20:
        raise DatasetFreezeError("final suite must contain exactly 20 cases")
    if composition["direct"] != 10 or composition["transitive"] != 10:
        raise DatasetFreezeError("final suite must contain 10 DIRECT and 10 TRANSITIVE cases")
    if any(case.split is not DatasetSplit.FINAL for case in suite.cases):
        raise DatasetFreezeError("every final case must use split FINAL")


def _relationship_valid(case: BenchmarkCase) -> bool:
    truth = case.ground_truth
    if truth is None:
        return False
    target = case.task.target_dependency
    same = (
        target.group_id == truth.breaking_dependency.group_id
        and target.artifact_id == truth.breaking_dependency.artifact_id
    )
    if case.case_type is BenchmarkCaseType.DIRECT:
        return same
    if case.case_type is BenchmarkCaseType.TRANSITIVE:
        return not same
    return False
