"""Small, explicit configuration defaults for BumpShield."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0
MAVEN_TIMEOUT_SECONDS = 600.0
MAX_REPAIR_ATTEMPTS = 3
REPAIR_PROVIDER_TIMEOUT_SECONDS = 900.0
DEFAULT_REPAIR_PROVIDER_EXECUTABLE = "codex"
SOURCE_CONTEXT_RADIUS = 20
RUNS_DIRECTORY_NAME = "runs"
BENCHMARKS_DIRECTORY_NAME = "benchmarks"
WORKSPACE_DIRECTORY_PREFIX = "bumpshield-workspaces-"
STATE_DIRECTORY_NAME = "bumpshield"
STATE_DIRECTORY_ENVIRONMENT_VARIABLE = "BUMPSHIELD_STATE_DIR"
XDG_STATE_HOME_ENVIRONMENT_VARIABLE = "XDG_STATE_HOME"


@dataclass(frozen=True, slots=True)
class BumpShieldConfig:
    """Runtime configuration with state external to analyzed repositories."""

    state_root: Path = field(default_factory=lambda: default_state_root())
    max_repair_attempts: int = MAX_REPAIR_ATTEMPTS
    repair_provider_timeout_seconds: float = REPAIR_PROVIDER_TIMEOUT_SECONDS
    repair_provider_executable: str = DEFAULT_REPAIR_PROVIDER_EXECUTABLE

    def __post_init__(self) -> None:
        normalized = Path(self.state_root).expanduser().resolve()
        object.__setattr__(self, "state_root", normalized)
        if self.max_repair_attempts < 1:
            raise ValueError("max_repair_attempts must be at least 1")
        if self.repair_provider_timeout_seconds <= 0:
            raise ValueError("repair_provider_timeout_seconds must be positive")
        if not self.repair_provider_executable.strip():
            raise ValueError("repair_provider_executable must not be empty")

    @property
    def runs_directory(self) -> Path:
        """Return external directory containing persistent run evidence."""
        return self.state_root / RUNS_DIRECTORY_NAME

    def run_directory(self, run_id: str) -> Path:
        """Return one run's artifact path without creating it."""
        return self.runs_directory / validate_run_id(run_id)

    @property
    def benchmarks_directory(self) -> Path:
        """Return external directory containing benchmark-run evidence."""
        return self.state_root / BENCHMARKS_DIRECTORY_NAME

    def benchmark_directory(self, run_id: str) -> Path:
        """Return one benchmark run path without creating it."""
        return self.benchmarks_directory / validate_run_id(run_id)


def default_state_root(
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve environment override, XDG state home, or platform fallback."""
    environment = os.environ if environ is None else environ
    override = environment.get(STATE_DIRECTORY_ENVIRONMENT_VARIABLE)
    if override:
        return Path(override).expanduser().resolve()

    xdg_state_home = environment.get(XDG_STATE_HOME_ENVIRONMENT_VARIABLE)
    if xdg_state_home:
        return (Path(xdg_state_home).expanduser() / STATE_DIRECTORY_NAME).resolve()

    home_directory = Path.home() if home is None else Path(home)
    return (home_directory / ".local" / "state" / STATE_DIRECTORY_NAME).resolve()


def validate_run_id(run_id: str) -> str:
    """Validate a run ID before using it in any filesystem path or prefix."""
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError("run_id must be a non-empty single path component")
    return run_id
