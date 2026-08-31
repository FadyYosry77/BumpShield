from __future__ import annotations

from pathlib import Path

from bumpshield.analysis.api_diff import (
    JavapParser,
    compare_relevant_api,
    reconstruct_dependency_path,
    safe_api_artifact_name,
)
from bumpshield.models import (
    ApiEvidenceKind,
    ApiMemberKind,
    DependencyCoordinate,
    DependencyNode,
    DependencyRelationship,
    DependencyUpgrade,
    FailureCategory,
    FailureSignal,
    TaskSpec,
)


OLD_API = """\
Compiled from "Parser.java"
public class org.example.Parser {
  public org.example.Parser();
  public org.example.Result parseValue(java.lang.String);
  public org.example.Result parse(java.lang.String);
  public org.example.Result parse(java.io.InputStream);
  public static final int DEFAULT;
}
"""


def failure(
    symbol: str,
    category: FailureCategory = FailureCategory.MISSING_SYMBOL,
    **values: str,
) -> FailureSignal:
    return FailureSignal(
        category=category,
        message="compiler failure",
        symbol=symbol,
        **values,
    )


def coordinates() -> tuple[DependencyCoordinate, DependencyCoordinate]:
    return (
        DependencyCoordinate("org.example", "parser", "1.0"),
        DependencyCoordinate("org.example", "parser", "2.0"),
    )


def test_javap_parser_preserves_methods_overloads_constructor_and_field() -> None:
    members = JavapParser().parse(OLD_API, "org.example.Parser")

    assert [item.kind for item in members].count(ApiMemberKind.METHOD) == 3
    assert [item.name for item in members].count("parse") == 2
    assert any(item.kind is ApiMemberKind.CONSTRUCTOR for item in members)
    field = next(item for item in members if item.kind is ApiMemberKind.FIELD)
    assert field.name == "DEFAULT"
    assert field.is_static
    assert "public static final int DEFAULT;" == field.declaration


def test_removed_method_is_strong_evidence() -> None:
    before, after = coordinates()
    old = JavapParser().parse(OLD_API, "org.example.Parser")
    new = JavapParser().parse(
        OLD_API.replace(
            "  public org.example.Result parseValue(java.lang.String);\n", ""
        ),
        "org.example.Parser",
    )

    evidence = compare_relevant_api(
        "org.example.Parser",
        failure("parseValue(java.lang.String)"),
        before,
        after,
        old,
        new,
    )

    assert evidence.kind is ApiEvidenceKind.REMOVED_MEMBER
    assert [item.name for item in evidence.old_members] == ["parseValue"]
    assert evidence.new_members == ()
    assert evidence.old_class_members == old
    assert evidence.new_class_members == new


def test_signature_change_preserves_old_and_new_overloads() -> None:
    before, after = coordinates()
    old = JavapParser().parse(OLD_API, "org.example.Parser")
    new_text = OLD_API.replace(
        "public org.example.Result parse(java.lang.String);",
        "public org.example.Result parse(java.lang.String, org.example.Options);",
    )
    new = JavapParser().parse(new_text, "org.example.Parser")

    evidence = compare_relevant_api(
        "org.example.Parser",
        failure(
            "parse",
            FailureCategory.METHOD_ARGUMENT_MISMATCH,
            found="java.lang.String",
            required="java.lang.String,org.example.Options",
        ),
        before,
        after,
        old,
        new,
    )

    assert evidence.kind is ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE
    assert any(item.parameter_types == ("java.lang.String",) for item in evidence.old_members)
    assert any(len(item.parameter_types) == 2 for item in evidence.new_members)


def test_unchanged_relevant_member_is_negative_evidence() -> None:
    before, after = coordinates()
    members = JavapParser().parse(OLD_API, "org.example.Parser")

    evidence = compare_relevant_api(
        "org.example.Parser",
        failure("parseValue(String)"),
        before,
        after,
        members,
        members,
    )

    assert evidence.kind is ApiEvidenceKind.RELEVANT_MEMBER_UNCHANGED


def test_target_overload_removal_is_not_hidden_by_other_overload() -> None:
    before, after = coordinates()
    old = JavapParser().parse(OLD_API, "org.example.Parser")
    new = JavapParser().parse(
        OLD_API.replace("  public org.example.Result parse(java.lang.String);\n", ""),
        "org.example.Parser",
    )

    evidence = compare_relevant_api(
        "org.example.Parser",
        failure("parse(java.lang.String)"),
        before,
        after,
        old,
        new,
    )

    assert evidence.kind is ApiEvidenceKind.CHANGED_MEMBER_SIGNATURE
    assert any(item.parameter_types == ("java.io.InputStream",) for item in evidence.new_members)


def test_added_method_and_removed_public_field_are_detected() -> None:
    before, after = coordinates()
    old = JavapParser().parse(OLD_API, "org.example.Parser")
    new_with_method = JavapParser().parse(
        OLD_API.replace(
            "  public static final int DEFAULT;",
            "  public static final int DEFAULT;\n  public void extra();",
        ),
        "org.example.Parser",
    )
    without_field = tuple(item for item in old if item.name != "DEFAULT")

    added = compare_relevant_api(
        "org.example.Parser",
        failure("extra()"),
        before,
        after,
        old,
        new_with_method,
    )
    removed_field = compare_relevant_api(
        "org.example.Parser",
        failure("DEFAULT"),
        before,
        after,
        old,
        without_field,
    )

    assert added.kind is ApiEvidenceKind.ADDED_MEMBER
    assert removed_field.kind is ApiEvidenceKind.REMOVED_MEMBER


def node(
    artifact: str,
    depth: int,
    parent: DependencyNode | None = None,
) -> DependencyNode:
    return DependencyNode(
        coordinate=DependencyCoordinate("org.example", artifact, "1"),
        relationship=(
            DependencyRelationship.DIRECT if depth == 1 else DependencyRelationship.TRANSITIVE
        ),
        depth=depth,
        parent=parent.key if parent else None,
    )


def task() -> TaskSpec:
    return TaskSpec(
        Path("/tmp/project"),
        "base",
        "updated",
        DependencyUpgrade("org.example", "A", "0", "1"),
    )


def test_dependency_path_reconstructs_real_target_chain_only() -> None:
    a = node("A", 1)
    b = node("B", 2, a)
    c = node("C", 3, b)
    other = node("Other", 1)
    outside = node("Outside", 2, other)

    path, target_on_path = reconstruct_dependency_path((a, b, c, other, outside), c.key, task())
    other_path, other_target = reconstruct_dependency_path(
        (a, b, c, other, outside), outside.key, task()
    )

    assert [item.artifact_id for item in path] == ["A", "B", "C"]
    assert target_on_path
    assert [item.artifact_id for item in other_path] == ["Other", "Outside"]
    assert not other_target


def test_broken_parent_path_stops_safely() -> None:
    broken = DependencyNode(
        DependencyCoordinate("org.example", "C", "1"),
        DependencyRelationship.TRANSITIVE,
        depth=3,
        parent=DependencyCoordinate("org.example", "Missing", "1").key,
    )

    path, _ = reconstruct_dependency_path((broken,), broken.key, task())

    assert [item.artifact_id for item in path] == ["C"]


def test_dependency_path_cycle_is_bounded() -> None:
    a_coordinate = DependencyCoordinate("org.example", "A", "1")
    b_coordinate = DependencyCoordinate("org.example", "B", "1")
    a = DependencyNode(
        a_coordinate,
        DependencyRelationship.TRANSITIVE,
        depth=2,
        parent=b_coordinate.key,
    )
    b = DependencyNode(
        b_coordinate,
        DependencyRelationship.TRANSITIVE,
        depth=2,
        parent=a_coordinate.key,
    )

    path, _ = reconstruct_dependency_path((a, b), a.key, task())

    assert len(path) == 2
    assert {item.artifact_id for item in path} == {"A", "B"}


def test_api_artifact_filename_blocks_traversal_and_is_deterministic() -> None:
    first = safe_api_artifact_name("../../evil/foo\\bar:Parser")
    second = safe_api_artifact_name("../../evil/foo\\bar:Parser")

    assert first == second
    assert "/" not in first and "\\" not in first and ".." not in first
    assert len(first) < 100
