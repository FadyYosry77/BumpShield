from pathlib import Path

import pytest

from bumpshield.analysis.dependency_diff import (
    DependencyTreeParseError,
    DependencyTreeParser,
    compare_dependency_trees,
)
from bumpshield.models import (
    DependencyChangeKind,
    DependencyRelationship,
    DependencyUpgrade,
    TaskSpec,
)


BASE_TREE = """\
org.example:app:jar:1.0
+- org.example:foo-core:jar:2.8.0:compile
|  +- org.example:foo-parser:jar:4.6.0:compile
|  \\- org.example:shared:jar:2.1.0:runtime
+- org.other:shared:jar:9.0.0:compile
\\- org.example:legacy:jar:3.4.1:test
"""

UPDATED_TREE = """\
org.example:app:jar:1.1
+- org.example:foo-core:jar:3.0.0:compile
|  +- org.example:foo-parser:jar:5.0.0:compile
|  +- org.example:shared:jar:2.1.0:compile
|  \\- org.example:new-helper:jar:1.0.0:runtime
\\- org.other:shared:jar:9.0.0:compile
"""


def task() -> TaskSpec:
    return TaskSpec(
        repository=Path("/tmp/example"),
        base_commit="base",
        updated_commit="updated",
        target_dependency=DependencyUpgrade(
            group_id="org.example",
            artifact_id="foo-core",
            old_version="2.8.0",
            new_version="3.0.0",
        ),
    )


def test_parser_preserves_depth_parent_relationship_classifier_and_noise() -> None:
    text = """\
[INFO] scanning projects
[INFO] org.example:app:jar:1.0
[INFO] +- org.example:direct:jar:1.0:compile
[INFO] |  +- org.example:nested:jar:tests:2.0:test
[WARNING] irrelevant warning
[INFO] |  \\- org.example:loser:jar:1.0:compile (omitted for conflict with 2.0)
[INFO] \\- org.example:other:jar:3.0:runtime
"""

    parsed = DependencyTreeParser().parse(text)

    assert [node.coordinate.artifact_id for node in parsed.nodes] == [
        "direct",
        "nested",
        "other",
    ]
    direct, nested, other = parsed.nodes
    assert direct.depth == 1
    assert direct.relationship is DependencyRelationship.DIRECT
    assert direct.parent is None
    assert nested.depth == 2
    assert nested.relationship is DependencyRelationship.TRANSITIVE
    assert nested.parent == direct.key
    assert nested.coordinate.classifier == "tests"
    assert other.relationship is DependencyRelationship.DIRECT


def test_parser_allows_a_valid_empty_dependency_tree() -> None:
    parsed = DependencyTreeParser().parse("org.example:empty:jar:1.0\n")

    assert parsed.nodes == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[INFO] no tree here\n", "no Maven project root"),
        (
            "org.example:one:jar:1\norg.example:two:jar:1\n",
            "multi-module",
        ),
        (
            "org.example:app:jar:1\n+- broken:coordinate\n",
            "unsupported dependency coordinate",
        ),
    ],
)
def test_parser_rejects_unsafe_or_malformed_trees(text: str, message: str) -> None:
    with pytest.raises(DependencyTreeParseError, match=message):
        DependencyTreeParser().parse(text)


def test_diff_classifies_updates_scope_add_remove_and_unchanged() -> None:
    parser = DependencyTreeParser()
    before = parser.parse(BASE_TREE).nodes
    after = parser.parse(UPDATED_TREE).nodes

    diff = compare_dependency_trees(before, after, task())

    assert len(diff.of_kind(DependencyChangeKind.UPDATED)) == 3
    assert len(diff.of_kind(DependencyChangeKind.ADDED)) == 1
    assert len(diff.of_kind(DependencyChangeKind.REMOVED)) == 1
    assert len(diff.of_kind(DependencyChangeKind.UNCHANGED)) == 1
    target_change = next(change for change in diff.changes if change.is_target)
    assert target_change.kind is DependencyChangeKind.UPDATED
    assert target_change.relationship is DependencyRelationship.DIRECT
    assert target_change.before is not None
    assert target_change.after is not None
    assert target_change.before.version == "2.8.0"
    assert target_change.after.version == "3.0.0"
    scope_change = next(
        change
        for change in diff.changes
        if (change.after or change.before).artifact_id == "shared"
        and (change.after or change.before).group_id == "org.example"
    )
    assert scope_change.kind is DependencyChangeKind.UPDATED
    assert scope_change.before_scope == "runtime"
    assert scope_change.after_scope == "compile"
    assert len(diff.transitive_updates) == 2
    assert diff.target is not None and diff.target.matched


def test_identity_uses_group_type_and_classifier_but_not_version() -> None:
    parser = DependencyTreeParser()
    before = parser.parse(
        """org.example:app:jar:1
+- one:shared:jar:tests:1.0:test
\\- two:shared:jar:1.0:compile
"""
    ).nodes
    after = parser.parse(
        """org.example:app:jar:1
+- one:shared:jar:tests:2.0:test
\\- two:shared:jar:1.0:compile
"""
    ).nodes

    diff = compare_dependency_trees(before, after, task())

    assert len(diff.of_kind(DependencyChangeKind.UPDATED)) == 1
    assert len(diff.of_kind(DependencyChangeKind.UNCHANGED)) == 1


def test_target_resolution_mismatch_is_structured() -> None:
    parser = DependencyTreeParser()
    before = parser.parse(BASE_TREE.replace("2.8.0", "2.7.0")).nodes
    after = parser.parse(UPDATED_TREE).nodes

    diff = compare_dependency_trees(before, after, task())

    assert diff.target is not None
    assert diff.target.resolved_base_version == "2.7.0"
    assert diff.target.resolved_updated_version == "3.0.0"
    assert not diff.target.matched
