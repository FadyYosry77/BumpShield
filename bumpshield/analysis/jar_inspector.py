"""Read-only class and package ownership checks for JAR archives."""

from __future__ import annotations

import zipfile
from pathlib import Path


class JarInspectionError(RuntimeError):
    """Raised when a reported artifact cannot be inspected safely."""


class JarInspector:
    """Inspect archive directories without extracting or executing dependency code."""

    def class_present(self, artifact: Path, class_name: str) -> bool:
        """Return whether exact class entry exists; inner classes do not substitute."""
        entries = self._entries(artifact)
        direct = class_name.replace(".", "/") + ".class"
        if direct in entries:
            return True
        parts = class_name.split(".")
        class_index = next(
            (index for index, part in enumerate(parts) if part[:1].isupper()),
            None,
        )
        if class_index is None or class_index == len(parts) - 1:
            return False
        nested = "/".join(parts[:class_index])
        if nested:
            nested += "/"
        nested += "$".join(parts[class_index:]) + ".class"
        return nested in entries

    def package_present(self, artifact: Path, package_name: str) -> bool:
        """Return whether archive has at least one class directly under a package."""
        prefix = package_name.replace(".", "/").rstrip("/") + "/"
        return any(
            name.startswith(prefix)
            and name.endswith(".class")
            and not name.endswith("/")
            for name in self._entries(artifact)
        )

    @staticmethod
    def _entries(artifact: Path) -> frozenset[str]:
        path = Path(artifact)
        if not path.is_file():
            raise JarInspectionError(f"artifact file does not exist: {path}")
        try:
            with zipfile.ZipFile(path) as archive:
                return frozenset(info.filename for info in archive.infolist())
        except (OSError, zipfile.BadZipFile) as error:
            raise JarInspectionError(
                f"artifact is not an inspectable JAR: {path}: {error}"
            ) from error
