from pathlib import Path

import pytest

from bumpshield.analysis.source_locator import SourceLocator
from bumpshield.models import FailureCategory, FailureSignal, StackFrame


def failure(
    reported_file: str,
    line: int = 3,
    *,
    frames: tuple[StackFrame, ...] = (),
) -> FailureSignal:
    return FailureSignal(
        category=FailureCategory.MISSING_SYMBOL,
        message="cannot find symbol",
        line=line,
        reported_file=reported_file,
        stack_frames=frames,
    )


def write_java(path: Path, line_count: int = 100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"// line {number}" for number in range(1, line_count + 1)]
    lines[0] = "package com.example.foo;"
    lines[1] = "import java.util.List;"
    lines[2] = "import org.example.Parser;"
    lines[3] = "import static org.example.Options.DEFAULT;"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_exact_relative_source_path_is_localized(tmp_path: Path) -> None:
    source = tmp_path / "src/main/java/com/example/Foo.java"
    write_java(source)

    localized = SourceLocator().localize(
        failure("src/main/java/com/example/Foo.java", 50),
        tmp_path,
    )

    assert localized.file == Path("src/main/java/com/example/Foo.java")


def test_absolute_path_inside_workspace_becomes_relative(tmp_path: Path) -> None:
    source = tmp_path / "src/main/java/com/example/Foo.java"
    write_java(source)

    localized = SourceLocator().localize(failure(str(source.resolve())), tmp_path)

    assert localized.file == Path("src/main/java/com/example/Foo.java")


@pytest.mark.parametrize("source_root", ["src/main/java", "src/test/java"])
def test_previous_workspace_path_maps_by_recognized_source_suffix(
    tmp_path: Path,
    source_root: str,
) -> None:
    relative = Path(source_root) / "com/example/Foo.java"
    write_java(tmp_path / relative)

    localized = SourceLocator().localize(
        failure(str(Path("/old/worktree") / relative)),
        tmp_path,
    )

    assert localized.file == relative


def test_previous_workspace_suffix_maps_unique_module_source(tmp_path: Path) -> None:
    relative = Path("module-a/src/main/java/com/example/Foo.java")
    write_java(tmp_path / relative)

    localized = SourceLocator().localize(
        failure("/old/worktree/module-a/src/main/java/com/example/Foo.java"),
        tmp_path,
    )

    assert localized.file == relative


def test_suffix_mapping_refuses_ambiguous_modules(tmp_path: Path) -> None:
    write_java(tmp_path / "module-a/src/main/java/com/example/Foo.java")
    write_java(tmp_path / "module-b/src/main/java/com/example/Foo.java")

    localized = SourceLocator().localize(
        failure("/old/worktree/src/main/java/com/example/Foo.java"),
        tmp_path,
    )

    assert localized.file is None


def test_missing_or_ambiguous_file_is_not_guessed(tmp_path: Path) -> None:
    write_java(tmp_path / "src/main/java/a/Foo.java")
    write_java(tmp_path / "src/main/java/b/Foo.java")
    locator = SourceLocator()

    missing = locator.localize(failure("Missing.java"), tmp_path)
    ambiguous = locator.localize(failure("Foo.java"), tmp_path)

    assert missing.file is None
    assert ambiguous.file is None


def test_fully_qualified_stack_frame_disambiguates_same_named_files(
    tmp_path: Path,
) -> None:
    write_java(tmp_path / "src/main/java/a/Foo.java")
    write_java(tmp_path / "src/main/java/b/Foo.java")
    frame = StackFrame("b.Foo", "run", "Foo.java", 8)

    localized = SourceLocator().localize(
        failure("Unknown.java", frames=(frame,)),
        tmp_path,
    )

    assert localized.file == Path("src/main/java/b/Foo.java")
    assert localized.line == 8


def test_dependency_stack_frame_does_not_map_by_basename(tmp_path: Path) -> None:
    write_java(tmp_path / "src/main/java/com/application/Parser.java")
    frame = StackFrame("org.dependency.Parser", "parse", "Parser.java", 12)

    localized = SourceLocator().localize(
        failure("Unknown.java", frames=(frame,)),
        tmp_path,
    )

    assert localized.file is None


def test_path_traversal_and_external_absolute_path_are_rejected(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.java"
    outside.write_text("secret", encoding="utf-8")
    locator = SourceLocator()

    traversal = locator.localize(failure("../../outside.java"), workspace)
    external = locator.localize(failure(str(outside.resolve())), workspace)

    assert traversal.file is None
    assert external.file is None
    assert locator.context_for(traversal, workspace) is None
    assert locator.context_for(external, workspace) is None


def test_symlink_escaping_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source_directory = workspace / "src/main/java/example"
    source_directory.mkdir(parents=True)
    outside = tmp_path / "outside.java"
    outside.write_text("secret", encoding="utf-8")
    (source_directory / "Escape.java").symlink_to(outside)

    localized = SourceLocator().localize(
        failure("src/main/java/example/Escape.java"),
        workspace,
    )

    assert localized.file is None


def test_context_window_uses_one_based_lines_and_extracts_java_header(
    tmp_path: Path,
) -> None:
    relative = Path("src/main/java/com/example/Foo.java")
    write_java(tmp_path / relative)
    locator = SourceLocator(context_radius=20)
    localized = locator.localize(failure(str(relative), 50), tmp_path)

    context = locator.context_for(localized, tmp_path)

    assert context is not None
    assert context.start_line == 30
    assert context.end_line == 70
    assert context.focus_line == 50
    assert context.lines[0].number == 30
    assert context.lines[-1].number == 70
    assert context.package == "com.example.foo"
    assert context.imports == (
        "java.util.List",
        "org.example.Parser",
        "static org.example.Options.DEFAULT",
    )


@pytest.mark.parametrize(
    ("focus", "expected_start", "expected_end"),
    [(1, 1, 4), (10, 7, 10)],
)
def test_context_window_clamps_to_file_boundaries(
    tmp_path: Path,
    focus: int,
    expected_start: int,
    expected_end: int,
) -> None:
    relative = Path("src/test/java/com/example/FooTest.java")
    write_java(tmp_path / relative, line_count=10)
    locator = SourceLocator(context_radius=3)
    localized = locator.localize(failure(str(relative), focus), tmp_path)

    context = locator.context_for(localized, tmp_path)

    assert context is not None
    assert context.start_line == expected_start
    assert context.end_line == expected_end


def test_out_of_range_line_localizes_file_without_reading_context(tmp_path: Path) -> None:
    relative = Path("src/main/java/com/example/Foo.java")
    write_java(tmp_path / relative, line_count=10)
    locator = SourceLocator()
    localized = locator.localize(failure(str(relative), 99), tmp_path)

    assert localized.file == relative
    assert locator.context_for(localized, tmp_path) is None
