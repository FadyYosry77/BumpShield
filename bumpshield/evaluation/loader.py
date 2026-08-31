"""Strict JSON loading for benchmark cases and suites."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseType,
    BenchmarkGroundTruth,
    BenchmarkProvenance,
    BenchmarkSource,
    BenchmarkSuite,
    DatasetSplit,
    GroundTruthDependency,
    StrategyId,
    UpgradeOrigin,
)
from bumpshield.models import DependencyUpgrade, MigrationKind, TaskSpec


class BenchmarkLoadError(ValueError):
    """Raised when benchmark JSON cannot produce typed models."""


def load_benchmark_suite(path: Path) -> BenchmarkSuite:
    """Load one suite and its referenced case files in declared order."""
    suite_path = Path(path).expanduser().resolve()
    data = _json_object(suite_path, "benchmark suite")
    raw_cases = data.get("cases")
    raw_strategies = data.get("strategies")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise BenchmarkLoadError("benchmark suite cases must be a non-empty list")
    if not isinstance(raw_strategies, list) or not raw_strategies:
        raise BenchmarkLoadError(
            "benchmark suite strategies must be a non-empty list"
        )
    cases: list[BenchmarkCase] = []
    for index, value in enumerate(raw_cases):
        if not isinstance(value, str) or not value.strip():
            raise BenchmarkLoadError(f"cases[{index}] must be a non-empty path")
        case_path = (suite_path.parent / value).resolve()
        try:
            case_path.relative_to(suite_path.parent)
        except ValueError as error:
            raise BenchmarkLoadError(
                f"case manifest escapes suite directory: {value}"
            ) from error
        cases.append(load_benchmark_case(case_path))
    evaluation_config = data.get("evaluation_config")
    if evaluation_config is not None and (
        not isinstance(evaluation_config, str) or not evaluation_config.strip()
    ):
        raise BenchmarkLoadError("evaluation_config must be a non-empty path")
    evaluation_config_path = (
        (suite_path.parent / evaluation_config).resolve()
        if evaluation_config is not None
        else None
    )
    if evaluation_config_path is not None:
        try:
            evaluation_config_path.relative_to(suite_path.parent)
        except ValueError as error:
            raise BenchmarkLoadError("evaluation_config escapes suite directory") from error
    dataset_lock_path = _relative_optional_path(data, "dataset_lock", suite_path)
    try:
        return BenchmarkSuite(
            id=_string(data, "id"),
            cases=tuple(cases),
            strategies=tuple(StrategyId(value) for value in raw_strategies),
            trials=_positive_int(data.get("trials", 1), "trials"),
            manifest_path=suite_path,
            evaluation_config_path=evaluation_config_path,
            dataset_lock_path=dataset_lock_path,
        )
    except (TypeError, ValueError) as error:
        raise BenchmarkLoadError(str(error)) from error


def load_benchmark_case(path: Path) -> BenchmarkCase:
    """Load one case while resolving repository relative to its manifest."""
    case_path = Path(path).expanduser().resolve()
    data = _json_object(case_path, "benchmark case")
    task_data = _mapping(data.get("task"), "task")
    dependency = _mapping(task_data.get("target_dependency"), "target_dependency")
    repository = Path(_string(task_data, "repository")).expanduser()
    if not repository.is_absolute():
        repository = case_path.parent / repository
    repository = repository.resolve()
    truth_data = data.get("ground_truth")
    truth = None
    if truth_data is not None:
        truth_mapping = _mapping(truth_data, "ground_truth")
        breaking = _mapping(
            truth_mapping.get("breaking_dependency"), "breaking_dependency"
        )
        try:
            truth = BenchmarkGroundTruth(
                breaking_dependency=GroundTruthDependency(
                    _string(breaking, "group_id"),
                    _string(breaking, "artifact_id"),
                    _string(breaking, "old_version"),
                    _string(breaking, "new_version"),
                ),
                failure_kind=MigrationKind(_string(truth_mapping, "failure_kind")),
                class_name=_optional_string(truth_mapping, "class"),
                member=_optional_string(truth_mapping, "member"),
            )
        except ValueError as error:
            raise BenchmarkLoadError(str(error)) from error
    tags = data.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise BenchmarkLoadError("tags must be a list of strings")
    provenance_data = data.get("provenance")
    provenance = None
    if provenance_data is not None:
        provenance_mapping = _mapping(provenance_data, "provenance")
        try:
            provenance = BenchmarkProvenance(
                project_name=_string(provenance_mapping, "project_name"),
                repository_url=_optional_string(provenance_mapping, "repository_url"),
                source_commit=_optional_string(provenance_mapping, "source_commit"),
                license=_optional_string(provenance_mapping, "license"),
                upgrade_origin=UpgradeOrigin(_string(provenance_mapping, "upgrade_origin")),
                ground_truth_basis=_string(provenance_mapping, "ground_truth_basis"),
            )
        except ValueError as error:
            raise BenchmarkLoadError(str(error)) from error
    try:
        task = TaskSpec(
            repository=repository,
            base_commit=_string(task_data, "base_commit"),
            updated_commit=_string(task_data, "updated_commit"),
            target_dependency=DependencyUpgrade(
                _string(dependency, "group_id"),
                _string(dependency, "artifact_id"),
                _string(dependency, "old_version"),
                _string(dependency, "new_version"),
            ),
        )
        return BenchmarkCase(
            id=_string(data, "id"),
            description=_string(data, "description"),
            task=task,
            case_type=BenchmarkCaseType(_string(data, "case_type")),
            source=BenchmarkSource(_string(data, "source")),
            split=DatasetSplit(data.get("split", "DEV")),
            ground_truth=truth,
            tags=tuple(tags),
            provenance=provenance,
        )
    except (TypeError, ValueError) as error:
        raise BenchmarkLoadError(str(error)) from error


def _json_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise BenchmarkLoadError(f"could not read {label} {path}: {error}") from error
    try:
        return _mapping(json.loads(raw), label)
    except json.JSONDecodeError as error:
        raise BenchmarkLoadError(
            f"invalid JSON in {path} at line {error.lineno}, column {error.colno}"
        ) from error


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkLoadError(f"{name} must be a JSON object")
    return value


def _string(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkLoadError(f"{name} must be a non-empty string")
    return value


def _optional_string(data: Mapping[str, Any], name: str) -> str | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkLoadError(f"{name} must be null or a non-empty string")
    return value


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise BenchmarkLoadError(f"{name} must be a positive integer")
    return value


def _relative_optional_path(
    data: Mapping[str, Any], name: str, suite_path: Path
) -> Path | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkLoadError(f"{name} must be a non-empty path")
    resolved = (suite_path.parent / value).resolve()
    try:
        resolved.relative_to(suite_path.parent)
    except ValueError as error:
        raise BenchmarkLoadError(f"{name} escapes suite directory") from error
    return resolved
