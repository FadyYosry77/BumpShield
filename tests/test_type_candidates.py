from __future__ import annotations

from pathlib import Path

from bumpshield.analysis.type_candidates import TypeCandidateExtractor
from bumpshield.models import (
    FailureCategory,
    FailureSignal,
    SourceContext,
    SourceLine,
    StackFrame,
    TypeCandidateOrigin,
)


def context(imports: tuple[str, ...], package: str = "com.example") -> SourceContext:
    return SourceContext(
        file=Path("src/main/java/com/example/Foo.java"),
        start_line=1,
        end_line=1,
        focus_line=1,
        lines=(SourceLine(1, "class Foo {}"),),
        package=package,
        imports=imports,
    )


def failure(**values: object) -> FailureSignal:
    return FailureSignal(
        category=values.pop("category", FailureCategory.MISSING_SYMBOL),
        message="cannot find symbol",
        **values,
    )


def test_concrete_location_type_beats_signature_platform_type(tmp_path: Path) -> None:
    candidates = TypeCandidateExtractor().extract(
        failure(
            symbol="parseValue(java.lang.String)",
            location="variable parser of type org.example.parser.Parser",
        ),
        context(("org.other.Parser",)),
        tmp_path,
    )

    assert [(item.name, item.origin) for item in candidates] == [
        ("org.example.parser.Parser", TypeCandidateOrigin.COMPILER_TYPE)
    ]


def test_explicit_wildcard_and_ambiguous_imports_are_preserved(tmp_path: Path) -> None:
    explicit = TypeCandidateExtractor().extract(
        failure(symbol="Parser"), context(("org.example.Parser",)), tmp_path
    )
    wildcard = TypeCandidateExtractor().extract(
        failure(symbol="Parser"), context(("org.example.*",)), tmp_path
    )
    ambiguous = TypeCandidateExtractor().extract(
        failure(symbol="Parser"),
        context(("one.Parser", "two.Parser")),
        tmp_path,
    )

    assert explicit[0].origin is TypeCandidateOrigin.EXPLICIT_IMPORT
    assert wildcard[0].name == "org.example.Parser"
    assert wildcard[0].origin is TypeCandidateOrigin.WILDCARD_IMPORT
    assert {item.name for item in ambiguous} == {"one.Parser", "two.Parser"}


def test_static_import_owner_and_stack_class(tmp_path: Path) -> None:
    static = TypeCandidateExtractor().extract(
        failure(symbol="DEFAULT"),
        context(("static org.example.Options.DEFAULT",)),
        tmp_path,
    )
    stack = TypeCandidateExtractor().extract(
        failure(
            category=FailureCategory.TEST_EXCEPTION,
            stack_frames=(StackFrame("org.example.Parser", "parse", "Parser.java", 9),),
        ),
        None,
        tmp_path,
    )
    wildcard_method = TypeCandidateExtractor().extract(
        failure(symbol="parseValue()"),
        context(("static org.example.Parser.*",)),
        tmp_path,
    )

    assert static[0].name == "org.example.Options"
    assert static[0].origin is TypeCandidateOrigin.STATIC_IMPORT
    assert stack[0].name == "org.example.Parser"
    assert wildcard_method[0].name == "org.example.Parser"


def test_project_owned_same_package_class_takes_precedence(tmp_path: Path) -> None:
    source = tmp_path / "src/main/java/com/example/Parser.java"
    source.parent.mkdir(parents=True)
    source.write_text("package com.example; class Parser {}", encoding="utf-8")

    candidates = TypeCandidateExtractor().extract(
        failure(symbol="Parser"),
        context(("org.dependency.Parser",)),
        tmp_path,
    )

    assert len(candidates) == 1
    assert candidates[0].name == "com.example.Parser"
    assert candidates[0].project_owned


def test_package_and_java_types_are_handled_without_guessing(tmp_path: Path) -> None:
    package = TypeCandidateExtractor().extract(
        failure(category=FailureCategory.PACKAGE_NOT_FOUND, symbol="org.legacy"),
        None,
        tmp_path,
    )
    java_type = TypeCandidateExtractor().extract(
        failure(location="variable text of type java.lang.String"),
        None,
        tmp_path,
    )

    assert package[0].is_package
    assert package[0].name == "org.legacy"
    assert java_type == ()
