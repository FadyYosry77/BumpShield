from dataclasses import replace
from pathlib import Path

from bumpshield.agent.investigator import DeterministicInvestigator
from bumpshield.analysis.source_usage import SourceUsageFinder
from bumpshield.models import (
    AffectedLocationKind,
    ApiEvidenceKind,
    FailureSignal,
    MigrationKind,
    SourceFileKind,
)
from test_investigator import make_bundle


def _write(workspace: Path, relative: str, text: str) -> Path:
    path = workspace / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _inputs(
    file: str,
    line: int,
    *,
    api_kind: ApiEvidenceKind = ApiEvidenceKind.REMOVED_MEMBER,
):
    bundle = make_bundle(api_kind)
    diagnosis = DeterministicInvestigator().investigate(bundle)
    hypothesis = diagnosis.primary_hypothesis
    assert hypothesis is not None
    assert hypothesis.failure is not None
    hypothesis = replace(
        hypothesis,
        failure=replace(hypothesis.failure, file=Path(file), line=line),
    )
    return hypothesis, bundle.api_evidence[0]


def test_method_search_distinguishes_primary_and_related_calls(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/main/java/example/Foo.java",
        "class Foo {\n  void run() {\n    parser.parseValue(value);\n  }\n}\n",
    )
    _write(
        tmp_path,
        "src/main/java/example/Bar.java",
        "class Bar {\n  void run() { parser.parseValue(other); }\n}\n",
    )
    _write(
        tmp_path,
        "src/main/java/example/Baz.java",
        "class Baz { void run() { parser.close(); } }\n",
    )
    hypothesis, api = _inputs("src/main/java/example/Foo.java", 3)

    locations = SourceUsageFinder().find(
        tmp_path, hypothesis, api, MigrationKind.REMOVED_METHOD
    )

    assert [(str(item.file), item.kind) for item in locations] == [
        ("src/main/java/example/Foo.java", AffectedLocationKind.PRIMARY_FAILURE),
        ("src/main/java/example/Bar.java", AffectedLocationKind.POTENTIAL_CALL_SITE),
    ]


def test_removed_class_finds_imports_and_test_source(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/main/java/example/Foo.java",
        "import org.example.parser.Parser;\nclass Foo { Parser parser; }\n",
    )
    _write(
        tmp_path,
        "src/test/java/example/FooTest.java",
        "class FooTest { Parser parser = new Parser(); }\n",
    )
    hypothesis, api = _inputs(
        "src/main/java/example/Foo.java", 2, api_kind=ApiEvidenceKind.REMOVED_CLASS
    )

    locations = SourceUsageFinder().find(
        tmp_path, hypothesis, api, MigrationKind.REMOVED_CLASS
    )

    import_location = next(
        item for item in locations if item.kind is AffectedLocationKind.EXACT_IMPORT
    )
    test_location = next(
        item for item in locations if item.file.name == "FooTest.java"
    )
    assert import_location.line == 1
    assert test_location.source_kind is SourceFileKind.TEST_SOURCE


def test_removed_package_finds_only_matching_imports(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "src/main/java/example/Foo.java",
        "import static org.example.parser.Legacy.VALUE;\n"
        "import org.other.Parser;\nclass Foo {}\n",
    )
    hypothesis, api = _inputs(
        "src/main/java/example/Foo.java", 3, api_kind=ApiEvidenceKind.PACKAGE_REMOVED
    )
    api = replace(api, class_name="org.example.parser")

    locations = SourceUsageFinder().find(
        tmp_path, hypothesis, api, MigrationKind.REMOVED_PACKAGE
    )

    assert [item.kind for item in locations] == [
        AffectedLocationKind.PRIMARY_FAILURE,
        AffectedLocationKind.EXACT_IMPORT,
    ]


def test_source_search_does_not_follow_escaping_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = _write(
        tmp_path,
        "outside/Secret.java",
        "class Secret { void leak() { parser.parseValue(secret); } }\n",
    )
    source_root = workspace / "src/main/java/example"
    source_root.mkdir(parents=True)
    (source_root / "Leak.java").symlink_to(outside)
    _write(
        workspace,
        "src/main/java/example/Foo.java",
        "class Foo { void run() { parser.parseValue(value); } }\n",
    )
    hypothesis, api = _inputs("src/main/java/example/Foo.java", 1)

    locations = SourceUsageFinder().find(
        workspace, hypothesis, api, MigrationKind.REMOVED_METHOD
    )

    assert {item.file.name for item in locations} == {"Foo.java"}


def test_generated_primary_is_classified_but_not_found_by_normal_scan(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "target/generated-sources/example/Foo.java",
        "class Foo { void run() { parser.parseValue(value); } }\n",
    )
    hypothesis, api = _inputs("target/generated-sources/example/Foo.java", 1)

    locations = SourceUsageFinder().find(
        tmp_path, hypothesis, api, MigrationKind.REMOVED_METHOD
    )

    assert len(locations) == 1
    assert locations[0].source_kind is SourceFileKind.GENERATED_SOURCE
