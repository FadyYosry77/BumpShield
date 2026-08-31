from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from bumpshield.analysis.jar_inspector import JarInspectionError, JarInspector


def make_jar(path: Path, entries: tuple[str, ...]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for entry in entries:
            archive.writestr(entry, b"fixture")


def test_exact_class_package_and_unsafe_entry_checks(tmp_path: Path) -> None:
    jar = tmp_path / "parser.jar"
    make_jar(
        jar,
        (
            "org/example/parser/Parser.class",
            "org/example/parser/Parser$Inner.class",
            "org/example/parser/Options.class",
            "../../evil.class",
        ),
    )
    inspector = JarInspector()

    assert inspector.class_present(jar, "org.example.parser.Parser")
    assert not inspector.class_present(jar, "org.example.parser.Missing")
    assert inspector.class_present(jar, "org.example.parser.Parser.Inner")
    assert inspector.package_present(jar, "org.example.parser")
    assert not inspector.package_present(jar, "org.example.missing")
    assert not (tmp_path.parent / "evil.class").exists()


def test_missing_and_invalid_jars_are_structured(tmp_path: Path) -> None:
    with pytest.raises(JarInspectionError, match="does not exist"):
        JarInspector().class_present(tmp_path / "missing.jar", "example.Parser")
    invalid = tmp_path / "invalid.jar"
    invalid.write_text("not zip", encoding="utf-8")
    with pytest.raises(JarInspectionError, match="not an inspectable JAR"):
        JarInspector().class_present(invalid, "example.Parser")
