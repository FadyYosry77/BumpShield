from __future__ import annotations

import json
from pathlib import Path

import pytest

from bumpshield.task_io import TaskSpecLoadError, load_task_spec, task_spec_to_dict


def write_task(path: Path, repository: str) -> None:
    path.write_text(
        json.dumps(
            {
                "repository": repository,
                "base_commit": "abc123",
                "updated_commit": "def456",
                "target_dependency": {
                    "group_id": "org.example",
                    "artifact_id": "foo",
                    "old_version": "2.8.0",
                    "new_version": "3.0.0",
                },
            }
        ),
        encoding="utf-8",
    )


def test_load_task_spec_resolves_relative_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    task_path = tmp_path / "task.json"
    write_task(task_path, "repository")

    task = load_task_spec(task_path)

    assert task.repository == repository.resolve()
    assert task.base_commit == "abc123"
    assert task.target_dependency.artifact_id == "foo"
    assert task_spec_to_dict(task)["repository"] == str(repository.resolve())


def test_load_task_spec_rejects_invalid_json(tmp_path: Path) -> None:
    task_path = tmp_path / "task.json"
    task_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(TaskSpecLoadError, match="invalid JSON"):
        load_task_spec(task_path)


def test_load_task_spec_rejects_missing_required_field(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    task_path = tmp_path / "task.json"
    write_task(task_path, str(repository))
    data = json.loads(task_path.read_text(encoding="utf-8"))
    data["target_dependency"]["group_id"] = ""
    task_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(TaskSpecLoadError, match="group_id"):
        load_task_spec(task_path)


def test_load_task_spec_rejects_missing_repository(tmp_path: Path) -> None:
    task_path = tmp_path / "task.json"
    write_task(task_path, "missing")

    with pytest.raises(TaskSpecLoadError, match="repository does not exist"):
        load_task_spec(task_path)


def test_load_task_spec_rejects_repository_file(tmp_path: Path) -> None:
    repository = tmp_path / "not-a-directory"
    repository.write_text("file", encoding="utf-8")
    task_path = tmp_path / "task.json"
    write_task(task_path, str(repository))

    with pytest.raises(TaskSpecLoadError, match="not a directory"):
        load_task_spec(task_path)

