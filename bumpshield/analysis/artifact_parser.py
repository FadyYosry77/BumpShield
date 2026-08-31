"""Parse Maven Dependency Plugin artifact lists with absolute filenames."""

from __future__ import annotations

from pathlib import Path

from bumpshield.models import DependencyCoordinate, ResolvedArtifact


class ArtifactListParseError(ValueError):
    """Raised when artifact-list evidence contains a malformed dependency line."""


class ArtifactListParser:
    """Parse ``dependency:list`` output produced with absolute filenames enabled.

    Supported lines are Maven's colon-separated forms:
    ``group:artifact:type:version:scope:absolute-path`` and
    ``group:artifact:type:classifier:version:scope:absolute-path``.
    Maven headings and other log noise are ignored.
    """

    def parse(self, text: str) -> tuple[ResolvedArtifact, ...]:
        artifacts: list[ResolvedArtifact] = []
        seen: set[tuple[object, ...]] = set()
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("[") or line.startswith("The following"):
                continue
            parsed = _parse_artifact_line(line)
            if parsed is None:
                continue
            coordinate, scope, path_text = parsed
            path = Path(path_text)
            if not path.is_absolute():
                raise ArtifactListParseError(
                    f"line {line_number}: artifact filename must be absolute"
                )
            artifact = ResolvedArtifact(coordinate, scope, path)
            identity = (coordinate.key, coordinate.version, scope, path)
            if identity not in seen:
                seen.add(identity)
                artifacts.append(artifact)
        return tuple(artifacts)


def _parse_artifact_line(
    line: str,
) -> tuple[DependencyCoordinate, str, str] | None:
    """Return one recognized dependency line; ignore unrelated Maven text."""
    parts = line.split(":")
    if len(parts) < 6:
        if len(parts) == 5 and all(parts[:3]):
            raise ArtifactListParseError(
                "dependency entry has no absolute artifact filename"
            )
        return None
    # Absolute Unix paths begin at token 5 or 6. Preserve any later colons.
    if parts[5].startswith("/"):
        group, artifact, dependency_type, version, scope = parts[:5]
        classifier = None
        path = ":".join(parts[5:])
    elif len(parts) >= 7 and parts[6].startswith("/"):
        group, artifact, dependency_type, classifier, version, scope = parts[:6]
        path = ":".join(parts[6:])
    else:
        # Coordinate-shaped lines missing absolute filename are unsafe evidence.
        if len(parts) in {5, 6} and all(parts[:3]):
            raise ArtifactListParseError("dependency entry has no absolute artifact filename")
        return None
    path = path.partition(" -- module ")[0].rstrip()
    if not all((group, artifact, dependency_type, version, scope, path)):
        raise ArtifactListParseError("dependency entry contains an empty field")
    return (
        DependencyCoordinate(
            group_id=group,
            artifact_id=artifact,
            version=version,
            type=dependency_type,
            classifier=classifier,
        ),
        scope,
        path,
    )
