from __future__ import annotations

from pathlib import Path

import pytest

from bumpshield.analysis.artifact_parser import ArtifactListParseError, ArtifactListParser


def test_artifact_list_parses_paths_classifiers_scopes_noise_and_groups() -> None:
    text = """\
[INFO] --- maven-dependency-plugin:list ---
The following files have been resolved:
   org.one:shared:jar:1.0:compile:/cache/org/one/shared-1.0.jar
   org.two:shared:jar:tests:2.0:test:/cache/org/two/shared-2.0-tests.jar
   org.three:runtime:jar:3.0:runtime:/cache/org/three/runtime-3.0.jar -- module runtime.auto
malformed irrelevant line
"""

    artifacts = ArtifactListParser().parse(text)

    assert len(artifacts) == 3
    assert artifacts[0].coordinate.group_id == "org.one"
    assert artifacts[0].path == Path("/cache/org/one/shared-1.0.jar")
    assert artifacts[1].coordinate.classifier == "tests"
    assert artifacts[1].scope == "test"
    assert artifacts[2].scope == "runtime"
    assert artifacts[2].path == Path("/cache/org/three/runtime-3.0.jar")


@pytest.mark.parametrize(
    "line",
    [
        "org.example:parser:jar:1.0:compile",
        "org.example:parser:jar:1.0:compile:relative.jar",
    ],
)
def test_artifact_list_rejects_missing_or_non_absolute_filename(line: str) -> None:
    with pytest.raises(ArtifactListParseError, match="artifact filename"):
        ArtifactListParser().parse(line)
