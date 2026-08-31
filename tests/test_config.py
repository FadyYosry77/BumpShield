from __future__ import annotations

from pathlib import Path

import pytest

from bumpshield.config import (
    BumpShieldConfig,
    STATE_DIRECTORY_ENVIRONMENT_VARIABLE,
    XDG_STATE_HOME_ENVIRONMENT_VARIABLE,
    default_state_root,
)


def test_xdg_state_home_is_respected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xdg_state_home = tmp_path / "xdg-state"
    monkeypatch.delenv(STATE_DIRECTORY_ENVIRONMENT_VARIABLE, raising=False)
    monkeypatch.setenv(XDG_STATE_HOME_ENVIRONMENT_VARIABLE, str(xdg_state_home))

    config = BumpShieldConfig()

    assert config.state_root == xdg_state_home / "bumpshield"


def test_state_root_falls_back_to_user_local_state(tmp_path: Path) -> None:
    home = tmp_path / "home"

    state_root = default_state_root(environ={}, home=home)

    assert state_root == home / ".local" / "state" / "bumpshield"


def test_environment_state_override_precedes_xdg(tmp_path: Path) -> None:
    override = tmp_path / "override"
    xdg_state_home = tmp_path / "xdg-state"

    state_root = default_state_root(
        environ={
            STATE_DIRECTORY_ENVIRONMENT_VARIABLE: str(override),
            XDG_STATE_HOME_ENVIRONMENT_VARIABLE: str(xdg_state_home),
        }
    )

    assert state_root == override


def test_explicit_state_root_wins_over_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_root = tmp_path / "environment"
    explicit_root = tmp_path / "explicit"
    monkeypatch.setenv(STATE_DIRECTORY_ENVIRONMENT_VARIABLE, str(environment_root))

    config = BumpShieldConfig(state_root=explicit_root)

    assert config.state_root == explicit_root
    assert config.runs_directory == explicit_root / "runs"
    assert config.run_directory("run-123") == explicit_root / "runs" / "run-123"


@pytest.mark.parametrize(
    "values",
    [
        {"max_repair_attempts": 0},
        {"repair_provider_timeout_seconds": 0},
        {"repair_provider_executable": "   "},
    ],
)
def test_invalid_repair_configuration_is_rejected(
    tmp_path: Path, values: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        BumpShieldConfig(state_root=tmp_path / "state", **values)
