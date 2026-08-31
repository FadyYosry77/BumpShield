"""Streamlit session-state keys for explicit, rerun-safe live actions."""

from __future__ import annotations

from typing import Any, MutableMapping

from demo_ui.adapters import TaskFormValues


DEFAULT_STATE: dict[str, Any] = {
    "demo_mode": "Recorded Verified Run",
    "page": "Overview",
    "replay_page": "Replay",
    "replay_scenario": "Synthetic Transitive Demo",
    "replay_started": False,
    "replay_step": 0,
    "replay_show_all": False,
    "replay_fast_view": False,
    "task": None,
    "reproduction_result": None,
    "planning_result": None,
    "repair_result": None,
    "investigation_running": False,
    "repair_running": False,
    "last_error": None,
    "show_technical_details": False,
}


def reset_replay_state(state: MutableMapping[str, Any]) -> None:
    """Return recorded walkthrough to its explicit start screen."""
    state["replay_started"] = False
    state["replay_step"] = 0
    state["replay_show_all"] = False
    state["replay_fast_view"] = False


FORM_KEYS = {
    "repository": "form_repository",
    "base_commit": "form_base_commit",
    "updated_commit": "form_updated_commit",
    "group_id": "form_group_id",
    "artifact_id": "form_artifact_id",
    "old_version": "form_old_version",
    "new_version": "form_new_version",
    "state_directory": "form_state_directory",
}


def initialize_state(state: MutableMapping[str, Any]) -> None:
    """Initialize missing keys without overwriting a live session."""
    for key, value in DEFAULT_STATE.items():
        if key not in state:
            state[key] = value
    for key in FORM_KEYS.values():
        if key not in state:
            state[key] = ""


def form_values(state: MutableMapping[str, Any]) -> TaskFormValues:
    """Read task fields from one initialized session mapping."""
    return TaskFormValues(
        **{name: str(state[key]) for name, key in FORM_KEYS.items()}
    )


def set_form_values(
    state: MutableMapping[str, Any],
    values: TaskFormValues,
) -> None:
    """Populate form fields without executing any BumpShield action."""
    for name, key in FORM_KEYS.items():
        state[key] = getattr(values, name)


def reset_run_state(state: MutableMapping[str, Any]) -> None:
    """Clear results when a user deliberately loads another task."""
    state["task"] = None
    state["reproduction_result"] = None
    state["planning_result"] = None
    state["repair_result"] = None
    state["last_error"] = None
    state["investigation_running"] = False
    state["repair_running"] = False
