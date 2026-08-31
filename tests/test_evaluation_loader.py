import json
from pathlib import Path

import pytest

from bumpshield.evaluation.loader import BenchmarkLoadError, load_benchmark_suite
from bumpshield.evaluation.models import BenchmarkCaseType, StrategyId


def _case(path: Path, repository: Path, case_id: str = "case-1") -> None:
    path.write_text(
        json.dumps(
            {
                "id": case_id,
                "description": "fixture",
                "task": {
                    "repository": str(repository),
                    "base_commit": "base",
                    "updated_commit": "updated",
                    "target_dependency": {
                        "group_id": "org.example",
                        "artifact_id": "core",
                        "old_version": "1",
                        "new_version": "2",
                    },
                },
                "case_type": "TRANSITIVE",
                "source": "SYNTHETIC_FIXTURE",
                "split": "DEV",
                "ground_truth": {
                    "breaking_dependency": {
                        "group_id": "org.example",
                        "artifact_id": "secret-parser",
                        "old_version": "4",
                        "new_version": "5",
                    },
                    "failure_kind": "REMOVED_METHOD",
                    "class": "org.example.Parser",
                    "member": "parseValue(java.lang.String)",
                },
                "tags": ["removed-method", "transitive"],
            }
        ),
        encoding="utf-8",
    )


def test_load_suite_and_typed_ground_truth(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    cases = tmp_path / "cases"
    cases.mkdir()
    _case(cases / "case.json", repository)
    suite_path = tmp_path / "suite.json"
    suite_path.write_text(
        json.dumps(
            {
                "id": "bump-dev-v1",
                "cases": ["cases/case.json"],
                "strategies": ["direct-one-shot", "bumpshield"],
            }
        ),
        encoding="utf-8",
    )

    suite = load_benchmark_suite(suite_path)

    assert suite.strategies == (
        StrategyId.DIRECT_ONE_SHOT,
        StrategyId.BUMPSHIELD,
    )
    assert suite.cases[0].case_type is BenchmarkCaseType.TRANSITIVE
    assert suite.cases[0].ground_truth.breaking_dependency.artifact_id == "secret-parser"


def test_suite_rejects_case_manifest_escape(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    outside = tmp_path / "outside.json"
    _case(outside, repository)
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    manifest = suite_dir / "suite.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "suite",
                "cases": ["../outside.json"],
                "strategies": ["bumpshield"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkLoadError, match="escapes"):
        load_benchmark_suite(manifest)


def test_invalid_manifest_is_clear(tmp_path: Path) -> None:
    path = tmp_path / "suite.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(BenchmarkLoadError, match="invalid JSON"):
        load_benchmark_suite(path)
