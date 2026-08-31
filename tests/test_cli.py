from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

from bumpshield.cli import (
    api_evidence_exit_code,
    diagnosis_exit_code,
    failure_exit_code,
    plan_exit_code,
    reproduction_exit_code,
)
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import (
    ApiAnalysisStatus,
    DiagnosisStatus,
    FailureAnalysisStatus,
    PlanStatus,
    ReproductionStatus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_cli_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "usage: bumpshield" in result.stdout
    assert "version" in result.stdout


def test_cli_version_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "version"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert result.stdout == "0.1.0\n"


def test_cli_reproduce_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "reproduce", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "task_json" in result.stdout
    assert "--state-dir" in result.stdout


def test_cli_dependencies_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "dependencies", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "task_json" in result.stdout
    assert "--state-dir" in result.stdout


def test_cli_failures_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "failures", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "task_json" in result.stdout
    assert "--state-dir" in result.stdout


def test_cli_evidence_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "evidence", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "task_json" in result.stdout
    assert "--state-dir" in result.stdout


def test_cli_diagnose_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "diagnose", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "task_json" in result.stdout
    assert "--state-dir" in result.stdout


def test_cli_plan_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "plan", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "task_json" in result.stdout
    assert "--state-dir" in result.stdout


def test_cli_repair_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "repair", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "task_json" in result.stdout
    assert "--state-dir" in result.stdout


def test_cli_benchmark_help_works() -> None:
    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "benchmark", "--help"],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "suite_json" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--resume" in result.stdout


def test_cli_benchmark_dry_run_has_no_execution(tmp_path: Path) -> None:
    repository = tmp_path / "not-a-git-repository"
    case_path = tmp_path / "case.json"
    suite_path = tmp_path / "suite.json"
    case_path.write_text(
        json.dumps(
            {
                "id": "case",
                "description": "dry run only",
                "task": {
                    "repository": str(repository),
                    "base_commit": "missing-base",
                    "updated_commit": "missing-updated",
                    "target_dependency": {
                        "group_id": "org.example",
                        "artifact_id": "core",
                        "old_version": "1",
                        "new_version": "2",
                    },
                },
                "case_type": "DIRECT",
                "source": "SYNTHETIC_FIXTURE",
            }
        ),
        encoding="utf-8",
    )
    suite_path.write_text(
        json.dumps(
            {
                "id": "suite",
                "cases": ["case.json"],
                "strategies": ["direct-one-shot", "bumpshield"],
            }
        ),
        encoding="utf-8",
    )

    result = CommandRunner().run(
        [
            sys.executable,
            "-m",
            "bumpshield.cli",
            "benchmark",
            str(suite_path),
            "--dry-run",
        ],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 0
    assert "Maximum provider calls: 4" in result.stdout
    assert "No repair execution performed" in result.stdout


def test_reproduction_exit_codes_are_stable() -> None:
    assert reproduction_exit_code(ReproductionStatus.CONFIRMED) == 0
    assert reproduction_exit_code(ReproductionStatus.BASE_FAILED) == 2
    assert reproduction_exit_code(ReproductionStatus.UPDATED_PASSED) == 2
    assert reproduction_exit_code(ReproductionStatus.EXECUTION_ERROR) == 1


def test_failure_analysis_exit_codes_are_stable() -> None:
    assert failure_exit_code(FailureAnalysisStatus.FAILURES_LOCALIZED) == 0
    assert failure_exit_code(FailureAnalysisStatus.NO_FAILURE) == 2
    assert failure_exit_code(FailureAnalysisStatus.FAILURE_UNLOCALIZED) == 2
    assert failure_exit_code(FailureAnalysisStatus.FAILURES_PARSED_PARTIALLY) == 2
    assert failure_exit_code(FailureAnalysisStatus.TIMEOUT) == 1
    assert failure_exit_code(FailureAnalysisStatus.EXECUTION_ERROR) == 1


def test_api_evidence_exit_codes_are_small_and_stable() -> None:
    assert api_evidence_exit_code(ApiAnalysisStatus.API_EVIDENCE_FOUND) == 0
    for status in ApiAnalysisStatus:
        if status is not ApiAnalysisStatus.API_EVIDENCE_FOUND:
            assert api_evidence_exit_code(status) == 2


def test_diagnosis_exit_codes_are_small_and_stable() -> None:
    assert diagnosis_exit_code(DiagnosisStatus.SUPPORTED_DIAGNOSIS) == 0
    for status in DiagnosisStatus:
        if status is not DiagnosisStatus.SUPPORTED_DIAGNOSIS:
            assert diagnosis_exit_code(status) == 2


def test_plan_exit_codes_are_small_and_stable() -> None:
    assert plan_exit_code(PlanStatus.PLAN_READY) == 0
    for status in PlanStatus:
        if status is not PlanStatus.PLAN_READY:
            assert plan_exit_code(status) == 2


def test_cli_reproduce_invalid_task_returns_infrastructure_exit(tmp_path: Path) -> None:
    task_path = tmp_path / "task.json"
    task_path.write_text("not-json", encoding="utf-8")

    result = CommandRunner().run(
        [sys.executable, "-m", "bumpshield.cli", "reproduce", str(task_path)],
        cwd=PROJECT_ROOT,
        timeout=5,
    )

    assert result.exit_code == 1
    assert "invalid JSON" in result.stderr


def test_cli_reproduce_confirms_fixture_without_real_maven(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "init", "--quiet")
    run_git(runner, repository, "config", "user.name", "BumpShield Tests")
    run_git(runner, repository, "config", "user.email", "tests@example.invalid")
    wrapper = repository / "mvnw"
    wrapper.write_text("#!/bin/sh\necho base-pass\nexit 0\n", encoding="utf-8")
    wrapper.chmod(0o755)
    run_git(runner, repository, "add", "mvnw")
    run_git(runner, repository, "commit", "--quiet", "-m", "base")
    base_commit = git_output(runner, repository, "rev-parse", "HEAD")
    wrapper.write_text("#!/bin/sh\necho updated-fail >&2\nexit 1\n", encoding="utf-8")
    run_git(runner, repository, "add", "mvnw")
    run_git(runner, repository, "commit", "--quiet", "-m", "updated")
    updated_commit = git_output(runner, repository, "rev-parse", "HEAD")
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "repository": str(repository),
                "base_commit": base_commit,
                "updated_commit": updated_commit,
                "target_dependency": {
                    "group_id": "org.example",
                    "artifact_id": "foo",
                    "old_version": "1.0",
                    "new_version": "2.0",
                },
            }
        ),
        encoding="utf-8",
    )
    state_root = tmp_path / "state"

    result = runner.run(
        [
            sys.executable,
            "-m",
            "bumpshield.cli",
            "reproduce",
            str(task_path),
            "--state-dir",
            str(state_root),
        ],
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    assert result.exit_code == 0
    assert "Regression: CONFIRMED" in result.stdout
    assert f"Artifacts: {state_root / 'runs'}" in result.stdout
    run_directories = list((state_root / "runs").iterdir())
    assert len(run_directories) == 1
    assert (run_directories[0] / "reproduction.json").is_file()
    assert not (repository / ".bumpshield").exists()


def test_cli_dependencies_compares_fixture_without_real_maven(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "init", "--quiet")
    run_git(runner, repository, "config", "user.name", "BumpShield Tests")
    run_git(runner, repository, "config", "user.email", "tests@example.invalid")
    wrapper = repository / "mvnw"
    wrapper.write_text(
        """#!/bin/sh
[ "$2" = "dependency:tree" ] || exit 9
for argument in "$@"; do
  case "$argument" in
    -DoutputFile=*) output_file=${argument#-DoutputFile=} ;;
  esac
done
cp dependency-tree.txt "$output_file"
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    (repository / "dependency-tree.txt").write_text(
        "org.example:app:jar:1\n"
        "+- org.example:foo:jar:1.0:compile\n"
        "\\- org.example:helper:jar:1.0:runtime\n",
        encoding="utf-8",
    )
    run_git(runner, repository, "add", ".")
    run_git(runner, repository, "commit", "--quiet", "-m", "base")
    base_commit = git_output(runner, repository, "rev-parse", "HEAD")
    (repository / "dependency-tree.txt").write_text(
        "org.example:app:jar:2\n"
        "+- org.example:foo:jar:2.0:compile\n"
        "\\- org.example:helper:jar:2.0:runtime\n",
        encoding="utf-8",
    )
    run_git(runner, repository, "add", "dependency-tree.txt")
    run_git(runner, repository, "commit", "--quiet", "-m", "updated")
    updated_commit = git_output(runner, repository, "rev-parse", "HEAD")
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "repository": str(repository),
                "base_commit": base_commit,
                "updated_commit": updated_commit,
                "target_dependency": {
                    "group_id": "org.example",
                    "artifact_id": "foo",
                    "old_version": "1.0",
                    "new_version": "2.0",
                },
            }
        ),
        encoding="utf-8",
    )
    state_root = tmp_path / "state"

    result = runner.run(
        [
            sys.executable,
            "-m",
            "bumpshield.cli",
            "dependencies",
            str(task_path),
            "--state-dir",
            str(state_root),
        ],
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    assert result.exit_code == 0, result.stderr
    assert "BumpShield Dependency Analysis" in result.stdout
    assert "Target matched: yes" in result.stdout
    assert "[TARGET/DIRECT] org.example:foo 1.0 -> 2.0" in result.stdout
    assert "[DIRECT] org.example:helper 1.0 -> 2.0" in result.stdout
    assert f"Artifacts: {state_root / 'runs'}" in result.stdout
    run_directories = list((state_root / "runs").iterdir())
    assert len(run_directories) == 1
    assert (run_directories[0] / "dependency-diff.json").is_file()
    assert not (repository / ".bumpshield").exists()


def test_cli_dependencies_returns_two_for_target_mismatch(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "init", "--quiet")
    run_git(runner, repository, "config", "user.name", "BumpShield Tests")
    run_git(runner, repository, "config", "user.email", "tests@example.invalid")
    wrapper = repository / "mvnw"
    wrapper.write_text(
        "#!/bin/sh\nfor argument in \"$@\"; do case \"$argument\" in "
        "-DoutputFile=*) output_file=${argument#-DoutputFile=} ;; esac; done\n"
        "cp dependency-tree.txt \"$output_file\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    (repository / "dependency-tree.txt").write_text(
        "org.example:app:jar:1\n+- org.example:foo:jar:1.0:compile\n",
        encoding="utf-8",
    )
    run_git(runner, repository, "add", ".")
    run_git(runner, repository, "commit", "--quiet", "-m", "only")
    commit = git_output(runner, repository, "rev-parse", "HEAD")
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "repository": str(repository),
                "base_commit": commit,
                "updated_commit": commit,
                "target_dependency": {
                    "group_id": "org.example",
                    "artifact_id": "foo",
                    "old_version": "1.0",
                    "new_version": "2.0",
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.run(
        [
            sys.executable,
            "-m",
            "bumpshield.cli",
            "dependencies",
            str(task_path),
            "--state-dir",
            str(tmp_path / "state"),
        ],
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    assert result.exit_code == 2
    assert "Target matched: no" in result.stdout


def test_cli_failures_localizes_fixture_without_real_maven(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "init", "--quiet")
    run_git(runner, repository, "config", "user.name", "BumpShield Tests")
    run_git(runner, repository, "config", "user.email", "tests@example.invalid")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(runner, repository, "add", ".")
    run_git(runner, repository, "commit", "--quiet", "-m", "base")
    base_commit = git_output(runner, repository, "rev-parse", "HEAD")
    source = repository / "src/main/java/com/example/Foo.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package com.example;\n\n"
        "import org.example.Parser;\n\n"
        "class Foo {\n"
        "    Object parse(Parser parser) { return parser.missing(); }\n"
        "}\n",
        encoding="utf-8",
    )
    wrapper = repository / "mvnw"
    wrapper.write_text(
        """#!/bin/sh
echo "[ERROR] $PWD/src/main/java/com/example/Foo.java:[6,48] cannot find symbol"
echo "[ERROR] symbol: method missing()"
echo "[ERROR] location: variable parser of type org.example.Parser" >&2
exit 1
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    run_git(runner, repository, "add", ".")
    run_git(runner, repository, "commit", "--quiet", "-m", "updated")
    updated_commit = git_output(runner, repository, "rev-parse", "HEAD")
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "repository": str(repository),
                "base_commit": base_commit,
                "updated_commit": updated_commit,
                "target_dependency": {
                    "group_id": "org.example",
                    "artifact_id": "parser",
                    "old_version": "1.0",
                    "new_version": "2.0",
                },
            }
        ),
        encoding="utf-8",
    )
    state_root = tmp_path / "state"

    result = runner.run(
        [
            sys.executable,
            "-m",
            "bumpshield.cli",
            "failures",
            str(task_path),
            "--state-dir",
            str(state_root),
        ],
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    assert result.exit_code == 0, result.stderr
    assert "BumpShield Failure Analysis" in result.stdout
    assert "MISSING_SYMBOL" in result.stdout
    assert "src/main/java/com/example/Foo.java:6:48" in result.stdout
    assert "missing()" in result.stdout
    assert ">    6 |" in result.stdout
    run_directories = list((state_root / "runs").iterdir())
    assert len(run_directories) == 1
    assert (run_directories[0] / "failure-analysis.json").is_file()
    assert not (repository / ".bumpshield").exists()


@pytest.mark.parametrize("command", ["evidence", "diagnose", "plan"])
def test_cli_evidence_and_diagnosis_without_real_java_or_maven(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    old_parser = tmp_path / "parser-old.jar"
    new_parser = tmp_path / "parser-new.jar"
    old_core = tmp_path / "core-old.jar"
    new_core = tmp_path / "core-new.jar"
    for jar, has_parser in (
        (old_parser, True),
        (new_parser, True),
        (old_core, False),
        (new_core, False),
    ):
        with zipfile.ZipFile(jar, "w") as archive:
            if has_parser:
                archive.writestr("org/example/parser/Parser.class", b"fixture")

    repository = tmp_path / "repository"
    repository.mkdir()
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "init", "--quiet")
    run_git(runner, repository, "config", "user.name", "BumpShield Tests")
    run_git(runner, repository, "config", "user.email", "tests@example.invalid")
    wrapper = repository / "mvnw"
    wrapper.write_text(
        """#!/bin/sh
for argument in "$@"; do
  case "$argument" in -DoutputFile=*) output_file=${argument#-DoutputFile=} ;; esac
done
case "$2" in
  dependency:tree) cp dependency-tree.txt "$output_file" ;;
  dependency:list) cp artifact-list.txt "$output_file" ;;
  test)
    echo "[ERROR] $PWD/src/main/java/com/example/Foo.java:[6,46] cannot find symbol"
    echo "[ERROR] symbol: method parseValue(java.lang.String)"
    echo "[ERROR] location: variable parser of type org.example.parser.Parser"
    exit 1 ;;
  *) exit 9 ;;
esac
""",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    (repository / "dependency-tree.txt").write_text(
        "org.example:app:jar:1\n"
        "+- org.example:core:jar:1.0:compile\n"
        "|  \\- org.example:parser:jar:4.0:compile\n",
        encoding="utf-8",
    )
    (repository / "artifact-list.txt").write_text(
        f"org.example:core:jar:1.0:compile:{old_core}\n"
        f"org.example:parser:jar:4.0:compile:{old_parser}\n",
        encoding="utf-8",
    )
    run_git(runner, repository, "add", ".")
    run_git(runner, repository, "commit", "--quiet", "-m", "base")
    base = git_output(runner, repository, "rev-parse", "HEAD")
    (repository / "dependency-tree.txt").write_text(
        "org.example:app:jar:2\n"
        "+- org.example:core:jar:2.0:compile\n"
        "|  \\- org.example:parser:jar:5.0:compile\n",
        encoding="utf-8",
    )
    (repository / "artifact-list.txt").write_text(
        f"org.example:core:jar:2.0:compile:{new_core}\n"
        f"org.example:parser:jar:5.0:compile:{new_parser}\n",
        encoding="utf-8",
    )
    source = repository / "src/main/java/com/example/Foo.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package com.example;\n\nimport org.example.parser.Parser;\n\n"
        "class Foo {\n  Object run(Parser parser) { return parser.parseValue(\"x\"); }\n}\n",
        encoding="utf-8",
    )
    related_source = repository / "src/main/java/com/example/Bar.java"
    related_source.write_text(
        "package com.example;\n"
        "class Bar { Object run(Parser parser) { return parser.parseValue(\"y\"); } }\n",
        encoding="utf-8",
    )
    run_git(runner, repository, "add", ".")
    run_git(runner, repository, "commit", "--quiet", "-m", "updated")
    updated = git_output(runner, repository, "rev-parse", "HEAD")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    javap = fake_bin / "javap"
    javap.write_text(
        """#!/bin/sh
echo 'public class org.example.parser.Parser {'
case "$3" in
  *old*) echo '  public org.example.Result parseValue(java.lang.String);' ;;
  *) echo '  public org.example.Result parse(java.lang.String, org.example.Options);' ;;
esac
echo '}'
""",
        encoding="utf-8",
    )
    javap.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    task_path = tmp_path / "task.json"
    task_path.write_text(
        json.dumps(
            {
                "repository": str(repository),
                "base_commit": base,
                "updated_commit": updated,
                "target_dependency": {
                    "group_id": "org.example",
                    "artifact_id": "core",
                    "old_version": "1.0",
                    "new_version": "2.0",
                },
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    status_before = None
    head_before = None
    source_before = None
    staged_before = None
    untracked_before = None
    if command == "plan":
        source.write_text(
            source.read_text(encoding="utf-8") + "// user change\n",
            encoding="utf-8",
        )
        (repository / "dependency-tree.txt").write_text(
            "staged user change\n", encoding="utf-8"
        )
        run_git(runner, repository, "add", "dependency-tree.txt")
        (repository / "untracked.txt").write_text("user file\n", encoding="utf-8")
        status_before = git_output(runner, repository, "status", "--porcelain=v1")
        head_before = git_output(runner, repository, "rev-parse", "HEAD")
        source_before = source.read_text(encoding="utf-8")
        staged_before = (repository / "dependency-tree.txt").read_text(encoding="utf-8")
        untracked_before = (repository / "untracked.txt").read_text(encoding="utf-8")

    result = runner.run(
        [
            sys.executable,
            "-m",
            "bumpshield.cli",
            command,
            str(task_path),
            "--state-dir",
            str(state),
        ],
        cwd=PROJECT_ROOT,
        timeout=15,
    )

    assert result.exit_code == 0, result.stderr
    if command == "evidence":
        assert "BumpShield API Evidence" in result.stdout
        assert "API evidence: REMOVED_MEMBER" in result.stdout
    elif command == "diagnose":
        assert "BumpShield Causal Diagnosis" in result.stdout
        assert "Diagnosis: SUPPORTED_DIAGNOSIS" in result.stdout
        assert "Evidence: VERY_STRONG" in result.stdout
    else:
        assert "BumpShield Migration Plan" in result.stdout
        assert "Diagnosis: SUPPORTED_DIAGNOSIS" in result.stdout
        assert "Migration: REMOVED_METHOD" in result.stdout
        assert "Plan status: PLAN_READY" in result.stdout
        assert "not verified replacements" in result.stdout
        assert "src/main/java/com/example/Bar.java:2" in result.stdout
    assert f"Artifacts: {state / 'runs'}" in result.stdout
    run_directories = list((state / "runs").iterdir())
    assert len(run_directories) == 1
    assert (run_directories[0] / "evidence-bundle.json").is_file()
    if command == "diagnose":
        assert (run_directories[0] / "hypotheses.json").is_file()
        assert (run_directories[0] / "causal-diagnosis.json").is_file()
        assert (run_directories[0] / "diagnosis.txt").is_file()
    if command == "plan":
        assert (run_directories[0] / "hypotheses.json").is_file()
        assert (run_directories[0] / "migration-plan.json").is_file()
        assert (run_directories[0] / "migration-plan.txt").is_file()
        assert (run_directories[0] / "repair-context.json").is_file()
        assert git_output(runner, repository, "status", "--porcelain=v1") == status_before
        assert git_output(runner, repository, "rev-parse", "HEAD") == head_before
        assert source.read_text(encoding="utf-8") == source_before
        assert (repository / "dependency-tree.txt").read_text(encoding="utf-8") == staged_before
        assert (repository / "untracked.txt").read_text(encoding="utf-8") == untracked_before
    assert not (repository / ".bumpshield").exists()


def run_git(runner: CommandRunner, cwd: Path, *arguments: str) -> None:
    result = runner.run(["git", *arguments], cwd=cwd, timeout=5)
    assert result.exit_code == 0, result.stderr


def git_output(runner: CommandRunner, cwd: Path, *arguments: str) -> str:
    result = runner.run(["git", *arguments], cwd=cwd, timeout=5)
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()
