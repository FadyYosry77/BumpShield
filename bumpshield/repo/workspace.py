"""Repository workspace foundation."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from bumpshield.config import WORKSPACE_DIRECTORY_PREFIX, validate_run_id
from bumpshield.execution.command_runner import CommandExecutionError
from bumpshield.models import WorkspaceKind
from bumpshield.repo.git import GitRepository, GitRepositoryError

LOGGER = logging.getLogger(__name__)


class WorkspaceError(RuntimeError):
    """Raised when managed workspace creation or cleanup fails."""


@dataclass(frozen=True, slots=True)
class RepositoryWorkspace:
    """Location and revision assigned to one workflow workspace role."""

    path: Path
    commit: str
    kind: WorkspaceKind

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not self.commit or not self.commit.strip():
            raise ValueError("commit must not be empty")


class WorkspaceManager:
    """Create and clean detached worktrees inside one owned temporary root."""

    def __init__(self, repository: GitRepository, run_id: str) -> None:
        self.repository = repository
        self.run_id = validate_run_id(run_id)
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix=f"{WORKSPACE_DIRECTORY_PREFIX}{self.run_id}-"
        )
        self.root = Path(self._temporary_directory.name)
        self._workspaces: list[RepositoryWorkspace] = []
        self._closed = False

    def create(self, commit: str, kind: WorkspaceKind) -> RepositoryWorkspace:
        """Create one detached worktree for a revision and workflow role."""
        if self._closed:
            raise WorkspaceError("workspace manager is already closed")
        destination = self.root / kind.value.lower()
        if destination.exists():
            raise WorkspaceError(f"workspace already exists: {destination}")
        LOGGER.debug("Creating %s workspace for %s at %s", kind, commit, destination)
        try:
            self.repository.add_detached_worktree(destination, commit)
        except (GitRepositoryError, CommandExecutionError) as error:
            raise WorkspaceError(str(error)) from error
        workspace = RepositoryWorkspace(path=destination, commit=commit, kind=kind)
        self._workspaces.append(workspace)
        return workspace

    def cleanup(self) -> None:
        """Remove only worktrees and temporary paths owned by this manager."""
        if self._closed:
            return
        errors: list[str] = []
        for workspace in reversed(self._workspaces):
            LOGGER.debug("Removing %s workspace at %s", workspace.kind, workspace.path)
            try:
                self.repository.remove_worktree(workspace.path)
            except (GitRepositoryError, CommandExecutionError) as error:
                LOGGER.error("Could not remove worktree %s: %s", workspace.path, error)
                errors.append(str(error))

        try:
            self._temporary_directory.cleanup()
        except OSError as error:
            LOGGER.error("Could not remove workspace root %s: %s", self.root, error)
            errors.append(str(error))

        try:
            self.repository.prune_worktrees()
        except (GitRepositoryError, CommandExecutionError) as error:
            LOGGER.error("Could not prune Git worktrees: %s", error)
            errors.append(str(error))

        self._closed = True
        if errors:
            raise WorkspaceError("workspace cleanup failed: " + "; ".join(errors))

    def __enter__(self) -> WorkspaceManager:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        try:
            self.cleanup()
        except WorkspaceError:
            if exc_value is None:
                raise
            LOGGER.exception("Workspace cleanup also failed; preserving original error")
        return False
