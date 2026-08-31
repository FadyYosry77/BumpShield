"""Repository and workspace abstractions."""

from bumpshield.repo.git import GitRepository, GitRepositoryError
from bumpshield.repo.workspace import RepositoryWorkspace, WorkspaceError, WorkspaceManager

__all__ = [
    "GitRepository",
    "GitRepositoryError",
    "RepositoryWorkspace",
    "WorkspaceError",
    "WorkspaceManager",
]
