from pathlib import Path

from bumpshield.agent.repairer import MigrationPlanner
from bumpshield.analysis.patch_analysis import PatchAnalyzer
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import PatchScopeStatus
from test_planner import _location, _planning_inputs
from test_reproducer import run_git


def _repository(path: Path) -> None:
    path.mkdir()
    runner = CommandRunner(default_timeout=5)
    run_git(runner, path, "init", "--quiet")
    run_git(runner, path, "config", "user.name", "BumpShield Tests")
    run_git(runner, path, "config", "user.email", "tests@example.invalid")
    source = path / "src/main/java/com/example/Foo.java"
    test = path / "src/test/java/com/example/FooTest.java"
    source.parent.mkdir(parents=True)
    test.parent.mkdir(parents=True)
    source.write_text("class Foo { int value() { return 1; } }\n", encoding="utf-8")
    test.write_text("class FooTest { }\n", encoding="utf-8")
    (path / "pom.xml").write_text("<project/>\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "initial")


def _plan():
    bundle, diagnosis = _planning_inputs()
    return MigrationPlanner().plan(bundle, diagnosis, (_location(),))


def test_patch_analyzer_uses_git_truth_and_counts_new_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _repository(root)
    analyzer = PatchAnalyzer()
    baseline = analyzer.capture_baseline(root)
    source = root / "src/main/java/com/example/Foo.java"
    source.write_text("class Foo { int value() { return 2; } }\n", encoding="utf-8")
    extra = root / "src/main/java/com/example/Extra.java"
    extra.write_text("class Extra {}\n", encoding="utf-8")

    result = analyzer.analyze(root, baseline, _plan())

    assert result.changed_files == (
        Path("src/main/java/com/example/Extra.java"),
        Path("src/main/java/com/example/Foo.java"),
    )
    assert result.added_files == (Path("src/main/java/com/example/Extra.java"),)
    assert result.stats.files_changed == 2
    assert result.stats.lines_added == 2
    assert result.stats.lines_removed == 1
    assert result.scope_status is PatchScopeStatus.OUT_OF_SCOPE
    assert "diff --git" in result.patch


def test_patch_analyzer_rejects_new_test_cheating_but_not_baseline_marker(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    _repository(root)
    test = root / "src/test/java/com/example/FooTest.java"
    test.write_text("@Disabled\nclass FooTest { }\n", encoding="utf-8")
    run_git(CommandRunner(), root, "add", ".")
    run_git(CommandRunner(), root, "commit", "--quiet", "-m", "disabled baseline")
    analyzer = PatchAnalyzer()
    baseline = analyzer.capture_baseline(root)
    (root / "src/main/java/com/example/Foo.java").write_text(
        "class Foo { int value() { return 2; } }\n", encoding="utf-8"
    )

    unchanged = analyzer.analyze(root, baseline, _plan())

    assert not unchanged.newly_disabled_test_files
    test.write_text("@Disabled\n@Ignore\nclass FooTest { }\n", encoding="utf-8")
    rejected = analyzer.analyze(root, baseline, _plan())
    assert rejected.newly_disabled_test_files == (
        Path("src/test/java/com/example/FooTest.java"),
    )
    assert "test disablement markers were introduced" in rejected.fatal_issues


def test_patch_analyzer_detects_test_deletion_and_skip_configuration(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    _repository(root)
    analyzer = PatchAnalyzer()
    baseline = analyzer.capture_baseline(root)
    (root / "src/test/java/com/example/FooTest.java").unlink()
    (root / "pom.xml").write_text(
        "<project><properties><skipTests>true</skipTests></properties></project>\n",
        encoding="utf-8",
    )

    result = analyzer.analyze(root, baseline, _plan())

    assert result.deleted_test_files == (
        Path("src/test/java/com/example/FooTest.java"),
    )
    assert result.test_skip_introduced
    assert len(result.fatal_issues) == 2
