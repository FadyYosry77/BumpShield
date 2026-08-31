import json
import shutil
from pathlib import Path

import pytest

from bumpshield.evaluation.dataset import (
    DatasetCaseValidation,
    DatasetFreezeError,
    DatasetValidationResult,
    verify_dataset_lock,
    write_dataset_lock,
)
from bumpshield.evaluation.loader import load_benchmark_suite
from bumpshield.evaluation.models import BenchmarkValidationStatus


def _final_suite(tmp_path: Path) -> Path:
    source_config = Path(__file__).parents[1] / "benchmark/final-config-v1.json"
    shutil.copyfile(source_config, tmp_path / "final-config-v1.json")
    cases = tmp_path / "cases"
    cases.mkdir()
    references = []
    for index in range(20):
        direct = index < 10
        case_id = f"final-case-{index:02d}"
        target = f"target-{index}"
        breaking = target if direct else f"breaking-{index}"
        manifest = {
            "id": case_id,
            "description": "final fixture",
            "task": {
                "repository": f"../runtime/{case_id}",
                "base_commit": "a" * 40,
                "updated_commit": "b" * 40,
                "target_dependency": {
                    "group_id": "org.example",
                    "artifact_id": target,
                    "old_version": "1",
                    "new_version": "2",
                },
            },
            "case_type": "DIRECT" if direct else "TRANSITIVE",
            "source": "SYNTHETIC_FIXTURE",
            "split": "FINAL",
            "ground_truth": {
                "breaking_dependency": {
                    "group_id": "org.example",
                    "artifact_id": breaking,
                    "old_version": "1",
                    "new_version": "2",
                },
                "failure_kind": "REMOVED_METHOD",
                "class": "org.example.Api",
                "member": "oldMethod(java.lang.String)",
            },
            "provenance": {
                "project_name": case_id,
                "repository_url": None,
                "source_commit": None,
                "license": None,
                "upgrade_origin": "CONSTRUCTED",
                "ground_truth_basis": "fixture source and javap comparison",
            },
            "tags": ["synthetic"],
        }
        path = cases / f"{case_id}.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        references.append(f"cases/{path.name}")
    suite = {
        "id": "BUMP-FINAL-v1",
        "cases": references,
        "strategies": ["direct-one-shot", "direct-retry", "bumpshield"],
        "trials": 1,
        "evaluation_config": "final-config-v1.json",
        "dataset_lock": "bump-final-v1.lock.json",
    }
    suite_path = tmp_path / "bump-final-v1.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")
    return suite_path


def test_final_dataset_lock_detects_manifest_drift(tmp_path: Path) -> None:
    suite_path = _final_suite(tmp_path)
    validation = DatasetValidationResult(
        "BUMP-FINAL-v1",
        tuple(
            DatasetCaseValidation(
                f"final-case-{index:02d}",
                BenchmarkValidationStatus.VALID,
                None,
                "CONFIRMED",
                True,
                True,
                True,
                True,
            )
            for index in range(20)
        ),
    )
    lock_path = tmp_path / "bump-final-v1.lock.json"

    written = write_dataset_lock(suite_path, lock_path, validation)
    suite = load_benchmark_suite(suite_path)
    verified = verify_dataset_lock(suite)

    assert written.dataset_hash == verified.dataset_hash
    assert verified.case_count == 20
    assert verified.direct_count == 10
    assert verified.transitive_count == 10

    case_path = tmp_path / "cases/final-case-00.json"
    data = json.loads(case_path.read_text(encoding="utf-8"))
    data["description"] = "tampered"
    case_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DatasetFreezeError, match="dataset hash"):
        verify_dataset_lock(load_benchmark_suite(suite_path))
