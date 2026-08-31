"""Loading and serialization for dependency migration task specifications."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bumpshield.models import DependencyUpgrade, TaskSpec


class TaskSpecLoadError(ValueError):
    """Raised when a task file cannot produce a valid ``TaskSpec``."""


def load_task_spec(path: Path) -> TaskSpec:
    """Load and validate required task fields from a JSON file.

    Relative repository paths are resolved from the task file's directory.
    Commit-object validation remains owned by the Git layer.
    """
    task_path = Path(path).expanduser().resolve()
    try:
        raw_text = task_path.read_text(encoding="utf-8")
    except OSError as error:
        raise TaskSpecLoadError(f"could not read task file {task_path}: {error}") from error

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise TaskSpecLoadError(
            f"invalid JSON in {task_path} at line {error.lineno}, column {error.colno}"
        ) from error

    task_data = _require_mapping(data, "task")
    dependency_data = _require_mapping(
        task_data.get("target_dependency"),
        "target_dependency",
    )
    repository_value = _require_string(task_data, "repository")
    repository = Path(repository_value).expanduser()
    if not repository.is_absolute():
        repository = task_path.parent / repository
    repository = repository.resolve()
    if not repository.exists():
        raise TaskSpecLoadError(f"repository does not exist: {repository}")
    if not repository.is_dir():
        raise TaskSpecLoadError(f"repository is not a directory: {repository}")

    try:
        dependency = DependencyUpgrade(
            group_id=_require_string(dependency_data, "group_id"),
            artifact_id=_require_string(dependency_data, "artifact_id"),
            old_version=_require_string(dependency_data, "old_version"),
            new_version=_require_string(dependency_data, "new_version"),
        )
        return TaskSpec(
            repository=repository,
            base_commit=_require_string(task_data, "base_commit"),
            updated_commit=_require_string(task_data, "updated_commit"),
            target_dependency=dependency,
        )
    except ValueError as error:
        raise TaskSpecLoadError(str(error)) from error


def task_spec_to_dict(task: TaskSpec) -> dict[str, object]:
    """Return canonical JSON-compatible task data."""
    return {
        "repository": str(task.repository),
        "base_commit": task.base_commit,
        "updated_commit": task.updated_commit,
        "target_dependency": {
            "group_id": task.target_dependency.group_id,
            "artifact_id": task.target_dependency.artifact_id,
            "old_version": task.target_dependency.old_version,
            "new_version": task.target_dependency.new_version,
        },
    }


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise TaskSpecLoadError(f"{field_name} must be a JSON object")
    return value


def _require_string(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise TaskSpecLoadError(f"{field_name} must be a non-empty string")
    return value
