from __future__ import annotations

import json
import zipfile
from pathlib import Path

from bumpshield.analysis.api_diff import ApiEvidenceAnalyzer
from bumpshield.agent.investigator import CausalDiagnoser
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.models import (
    ApiAnalysisStatus,
    ApiEvidenceKind,
    ClassOwnershipStatus,
    CommandResult,
    DependencyTreeCommandResult,
    DependencyUpgrade,
    ExecutionResult,
    ExecutionStatus,
    JavaApiCommandResult,
    ResolvedArtifactsCommandResult,
    TaskSpec,
)
from bumpshield.repo.workspace import RepositoryWorkspace


BASE_TREE = """\
org.example:app:jar:1
+- org.example:core:jar:1.0:compile
|  \\- org.example:parser:jar:1.0:compile
"""
UPDATED_TREE = """\
org.example:app:jar:2
+- org.example:core:jar:2.0:compile
|  \\- org.example:parser:jar:2.0:compile
"""
OLD_API = """\
public class org.example.parser.Parser {
  public org.example.Result parseValue(java.lang.String);
}
"""
NEW_API = """\
public class org.example.parser.Parser {
  public org.example.Result parse(java.lang.String, org.example.Options);
}
"""


def run_git(runner: CommandRunner, cwd: Path, *arguments: str) -> str:
    result = runner.run(("git", *arguments), cwd=cwd, timeout=5)
    assert result.exit_code == 0, result.stderr
    return result.stdout.strip()


def make_jar(path: Path, *, parser: bool = True) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        if parser:
            archive.writestr("org/example/parser/Parser.class", b"fixture")


def create_repository(
    path: Path,
    old_jar: Path,
    new_jar: Path,
    old_core: Path,
    new_core: Path,
) -> tuple[str, str]:
    runner = CommandRunner(default_timeout=5)
    path.mkdir()
    run_git(runner, path, "init", "--quiet")
    run_git(runner, path, "config", "user.name", "BumpShield Tests")
    run_git(runner, path, "config", "user.email", "tests@example.invalid")
    (path / "dependency-tree.txt").write_text(BASE_TREE, encoding="utf-8")
    (path / "artifact-list.txt").write_text(
        f"org.example:core:jar:1.0:compile:{old_core}\n"
        f"org.example:parser:jar:1.0:compile:{old_jar}\n",
        encoding="utf-8",
    )
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "base")
    base = run_git(runner, path, "rev-parse", "HEAD")

    (path / "dependency-tree.txt").write_text(UPDATED_TREE, encoding="utf-8")
    (path / "artifact-list.txt").write_text(
        f"org.example:core:jar:2.0:compile:{new_core}\n"
        f"org.example:parser:jar:2.0:compile:{new_jar}\n",
        encoding="utf-8",
    )
    source = path / "src/main/java/com/example/Foo.java"
    source.parent.mkdir(parents=True)
    source.write_text(
        "package com.example;\n\n"
        "import org.example.parser.Parser;\n\n"
        "class Foo {\n"
        "  Object run(Parser parser) { return parser.parseValue(\"x\"); }\n"
        "}\n",
        encoding="utf-8",
    )
    run_git(runner, path, "add", ".")
    run_git(runner, path, "commit", "--quiet", "-m", "updated")
    updated = run_git(runner, path, "rev-parse", "HEAD")
    return base, updated


class FixtureMaven:
    def __init__(self, *, package_failure: bool = False) -> None:
        self.package_failure = package_failure

    def dependency_tree(
        self, workspace: RepositoryWorkspace, output_file: Path
    ) -> DependencyTreeCommandResult:
        raw = (workspace.path / "dependency-tree.txt").read_text(encoding="utf-8")
        output_file.write_text(raw, encoding="utf-8")
        return DependencyTreeCommandResult(
            execution=self._execution(workspace, "dependency:tree", 0, "tree\n"),
            output_file=output_file,
            raw_output=raw,
        )

    def artifact_list(
        self, workspace: RepositoryWorkspace, output_file: Path
    ) -> ResolvedArtifactsCommandResult:
        raw = (workspace.path / "artifact-list.txt").read_text(encoding="utf-8")
        output_file.write_text(raw, encoding="utf-8")
        return ResolvedArtifactsCommandResult(
            execution=self._execution(workspace, "dependency:list", 0, "list\n"),
            output_file=output_file,
            raw_output=raw,
        )

    def execute(self, workspace: RepositoryWorkspace) -> ExecutionResult:
        source = workspace.path / "src/main/java/com/example/Foo.java"
        stdout = (
            f"[ERROR] {source}:[3,1] package org.example.legacy does not exist\n"
            if self.package_failure
            else (
                f"[ERROR] {source}:[6,46] cannot find symbol\n"
                "[ERROR] symbol: method parseValue(java.lang.String)\n"
                "[ERROR] location: variable parser of type org.example.parser.Parser\n"
            )
        )
        return self._execution(workspace, "test", 1, stdout)

    @staticmethod
    def _execution(
        workspace: RepositoryWorkspace, operation: str, exit_code: int, stdout: str
    ) -> ExecutionResult:
        command = CommandResult(
            command=("mvn", "-B", operation),
            cwd=workspace.path,
            exit_code=exit_code,
            stdout=stdout,
            stderr="",
            duration_seconds=0.1,
        )
        return ExecutionResult(
            status=ExecutionStatus.PASS if exit_code == 0 else ExecutionStatus.FAIL,
            commands=(command,),
        )


class FixtureJavap:
    def __init__(self) -> None:
        self.calls: list[Path] = []

    def inspect(self, artifact: Path, class_name: str) -> JavaApiCommandResult:
        self.calls.append(artifact)
        raw = OLD_API if "old" in artifact.name else NEW_API
        command = CommandResult(
            command=("javap", "-public", "-classpath", str(artifact), class_name),
            cwd=artifact.parent,
            exit_code=0,
            stdout=raw,
            stderr="",
            duration_seconds=0.1,
        )
        return JavaApiCommandResult(
            ExecutionResult(ExecutionStatus.PASS, (command,)),
            artifact,
            class_name,
            raw,
        )


class UnavailableJavap:
    def inspect(self, artifact: Path, class_name: str) -> JavaApiCommandResult:
        return JavaApiCommandResult(
            ExecutionResult(ExecutionStatus.ERROR, detail="javap missing"),
            artifact,
            class_name,
            "",
        )


def test_phase4_composes_existing_analysis_and_preserves_repository(
    tmp_path: Path,
) -> None:
    old_jar = tmp_path / "parser-old.jar"
    new_jar = tmp_path / "parser-new.jar"
    old_core = tmp_path / "core-old.jar"
    new_core = tmp_path / "core-new.jar"
    make_jar(old_jar)
    make_jar(new_jar)
    make_jar(old_core, parser=False)
    make_jar(new_core, parser=False)
    repository = tmp_path / "repository"
    base, updated = create_repository(
        repository, old_jar, new_jar, old_core, new_core
    )
    task = TaskSpec(
        repository,
        base,
        updated,
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
    )
    runner = CommandRunner(default_timeout=5)
    (repository / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
    (repository / "dependency-tree.txt").write_text("staged user edit\n", encoding="utf-8")
    run_git(runner, repository, "add", "dependency-tree.txt")
    (repository / "notes.txt").write_text("untracked\n", encoding="utf-8")
    status_before = run_git(runner, repository, "status", "--porcelain=v1")
    head_before = run_git(runner, repository, "rev-parse", "HEAD")
    index_before = run_git(runner, repository, "diff", "--cached", "--binary")
    state = tmp_path / "external-state"

    result = ApiEvidenceAnalyzer(
        maven=FixtureMaven(),
        javap=FixtureJavap(),
        config=BumpShieldConfig(state_root=state),
    ).analyze(task, run_id="evidence-run")

    assert result.status is ApiAnalysisStatus.API_EVIDENCE_FOUND
    attribution = next(
        item for item in result.attributions if item.candidate.name.endswith("Parser")
    )
    assert attribution.ownership is ClassOwnershipStatus.EXACT_SINGLE_MATCH
    assert attribution.target_on_path
    assert [item.coordinate.artifact_id for item in result.base_artifacts] == [
        "core",
        "parser",
    ]
    assert attribution.api_evidence[0].kind is ApiEvidenceKind.REMOVED_MEMBER
    assert [item.artifact_id for item in attribution.dependency_path] == ["core", "parser"]

    expected = state / "runs" / "evidence-run"
    required = {
        "task.json",
        "base-dependency-tree.txt",
        "updated-dependency-tree.txt",
        "base-artifact-list.txt",
        "updated-artifact-list.txt",
        "dependencies-before.json",
        "dependencies-after.json",
        "dependency-diff.json",
        "updated-build.log",
        "failures.json",
        "source-contexts.json",
        "resolved-artifacts-before.json",
        "resolved-artifacts-after.json",
        "class-attribution.json",
        "api-evidence.json",
        "evidence-bundle.json",
        "api",
    }
    assert {item.name for item in expected.iterdir()} == required
    assert len(list((expected / "api").iterdir())) == 2
    evidence = json.loads((expected / "api-evidence.json").read_text())
    assert evidence[0]["kind"] == "REMOVED_MEMBER"
    bundle = json.loads((expected / "evidence-bundle.json").read_text())
    assert bundle["primary_failure"]["symbol"] == "parseValue(java.lang.String)"
    assert not list(expected.rglob("*.jar"))

    assert run_git(runner, repository, "status", "--porcelain=v1") == status_before
    assert run_git(runner, repository, "rev-parse", "HEAD") == head_before
    assert run_git(runner, repository, "diff", "--cached", "--binary") == index_before
    assert (repository / "tracked.txt").read_text() == "unstaged\n"
    assert (repository / "notes.txt").read_text() == "untracked\n"
    assert not (repository / ".bumpshield").exists()
    worktrees = run_git(runner, repository, "worktree", "list", "--porcelain")
    assert worktrees.count("worktree ") == 1

    diagnosis = CausalDiagnoser(
        evidence_analyzer=ApiEvidenceAnalyzer(
            maven=FixtureMaven(),
            javap=FixtureJavap(),
            config=BumpShieldConfig(state_root=tmp_path / "diagnosis-state"),
        )
    ).diagnose(task, run_id="diagnosis-isolation-run")

    assert diagnosis.status.value == "SUPPORTED_DIAGNOSIS"
    assert run_git(runner, repository, "status", "--porcelain=v1") == status_before
    assert run_git(runner, repository, "rev-parse", "HEAD") == head_before
    assert run_git(runner, repository, "diff", "--cached", "--binary") == index_before
    assert (repository / "tracked.txt").read_text() == "unstaged\n"
    assert (repository / "notes.txt").read_text() == "untracked\n"
    assert not (repository / ".bumpshield").exists()
    assert run_git(runner, repository, "worktree", "list", "--porcelain").count("worktree ") == 1


def test_same_class_in_two_changed_dependencies_remains_ambiguous(
    tmp_path: Path,
) -> None:
    old_parser = tmp_path / "parser-old.jar"
    new_parser = tmp_path / "parser-new.jar"
    old_core = tmp_path / "core-old.jar"
    new_core = tmp_path / "core-new.jar"
    for jar in (old_parser, new_parser, old_core, new_core):
        make_jar(jar)
    repository = tmp_path / "repository"
    base, updated = create_repository(
        repository, old_parser, new_parser, old_core, new_core
    )
    task = TaskSpec(
        repository,
        base,
        updated,
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
    )
    javap = FixtureJavap()

    result = ApiEvidenceAnalyzer(
        maven=FixtureMaven(),
        javap=javap,
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).analyze(task, run_id="ambiguous-run")

    assert result.status is ApiAnalysisStatus.AMBIGUOUS_ATTRIBUTION
    attribution = result.attributions[0]
    assert attribution.ownership is ClassOwnershipStatus.MULTIPLE_MATCHES
    assert {item.after.artifact_id for item in attribution.dependencies if item.after} == {
        "core",
        "parser",
    }
    assert javap.calls == []


def test_missing_javap_is_unavailable_evidence_not_negative_evidence(
    tmp_path: Path,
) -> None:
    old_parser = tmp_path / "parser-old.jar"
    new_parser = tmp_path / "parser-new.jar"
    old_core = tmp_path / "core-old.jar"
    new_core = tmp_path / "core-new.jar"
    make_jar(old_parser)
    make_jar(new_parser)
    make_jar(old_core, parser=False)
    make_jar(new_core, parser=False)
    repository = tmp_path / "repository"
    base, updated = create_repository(
        repository, old_parser, new_parser, old_core, new_core
    )
    task = TaskSpec(
        repository,
        base,
        updated,
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
    )

    result = ApiEvidenceAnalyzer(
        maven=FixtureMaven(),
        javap=UnavailableJavap(),
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).analyze(task, run_id="no-javap-run")

    assert result.status is ApiAnalysisStatus.API_TOOL_UNAVAILABLE
    evidence = result.attributions[0].api_evidence[0]
    assert evidence.kind is ApiEvidenceKind.API_INSPECTION_UNAVAILABLE
    assert evidence.old_class_present and evidence.new_class_present
    raw_files = list((result.artifact_directory / "api").iterdir())
    assert len(raw_files) == 2
    assert all("javap missing" in item.read_text() for item in raw_files)


def test_project_owned_candidate_is_not_attributed_to_dependency_jar(
    tmp_path: Path,
) -> None:
    old_parser = tmp_path / "parser-old.jar"
    new_parser = tmp_path / "parser-new.jar"
    old_core = tmp_path / "core-old.jar"
    new_core = tmp_path / "core-new.jar"
    make_jar(old_parser)
    make_jar(new_parser)
    make_jar(old_core, parser=False)
    make_jar(new_core, parser=False)
    repository = tmp_path / "repository"
    base, _ = create_repository(
        repository, old_parser, new_parser, old_core, new_core
    )
    project_class = repository / "src/main/java/org/example/parser/Parser.java"
    project_class.parent.mkdir(parents=True)
    project_class.write_text(
        "package org.example.parser; public class Parser {}\n", encoding="utf-8"
    )
    runner = CommandRunner(default_timeout=5)
    run_git(runner, repository, "add", str(project_class.relative_to(repository)))
    run_git(runner, repository, "commit", "--quiet", "-m", "project class")
    updated = run_git(runner, repository, "rev-parse", "HEAD")
    task = TaskSpec(
        repository,
        base,
        updated,
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
    )

    result = ApiEvidenceAnalyzer(
        maven=FixtureMaven(),
        javap=FixtureJavap(),
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).analyze(task, run_id="project-owned-run")

    assert result.status is ApiAnalysisStatus.NO_CHANGED_DEPENDENCY_ATTRIBUTION
    assert result.attributions[0].ownership is ClassOwnershipStatus.PROJECT_OWNED
    assert result.attributions[0].dependencies == ()


def test_removed_class_and_package_are_distinct_api_evidence(tmp_path: Path) -> None:
    old_parser = tmp_path / "parser-old.jar"
    new_parser = tmp_path / "parser-new.jar"
    old_core = tmp_path / "core-old.jar"
    new_core = tmp_path / "core-new.jar"
    make_jar(old_parser)
    make_jar(new_parser, parser=False)
    make_jar(old_core, parser=False)
    make_jar(new_core, parser=False)
    repository = tmp_path / "repository"
    base, updated = create_repository(
        repository, old_parser, new_parser, old_core, new_core
    )
    task = TaskSpec(
        repository,
        base,
        updated,
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
    )

    class_result = ApiEvidenceAnalyzer(
        maven=FixtureMaven(),
        javap=FixtureJavap(),
        config=BumpShieldConfig(state_root=tmp_path / "class-state"),
    ).analyze(task, run_id="removed-class")

    assert class_result.attributions[0].api_evidence[0].kind is ApiEvidenceKind.REMOVED_CLASS

    with zipfile.ZipFile(old_parser, "w") as archive:
        archive.writestr("org/example/legacy/Legacy.class", b"fixture")
    package_result = ApiEvidenceAnalyzer(
        maven=FixtureMaven(package_failure=True),
        javap=FixtureJavap(),
        config=BumpShieldConfig(state_root=tmp_path / "package-state"),
    ).analyze(task, run_id="removed-package")

    assert package_result.attributions[0].candidate.is_package
    assert package_result.attributions[0].api_evidence[0].kind is ApiEvidenceKind.PACKAGE_REMOVED


def test_missing_new_artifact_never_becomes_false_removed_class(
    tmp_path: Path,
) -> None:
    old_parser = tmp_path / "parser-old.jar"
    missing_new_parser = tmp_path / "missing-parser-new.jar"
    old_core = tmp_path / "core-old.jar"
    new_core = tmp_path / "core-new.jar"
    make_jar(old_parser)
    make_jar(old_core, parser=False)
    make_jar(new_core, parser=False)
    repository = tmp_path / "repository"
    base, updated = create_repository(
        repository, old_parser, missing_new_parser, old_core, new_core
    )
    task = TaskSpec(
        repository,
        base,
        updated,
        DependencyUpgrade("org.example", "core", "1.0", "2.0"),
    )

    result = ApiEvidenceAnalyzer(
        maven=FixtureMaven(),
        javap=FixtureJavap(),
        config=BumpShieldConfig(state_root=tmp_path / "state"),
    ).analyze(task, run_id="missing-artifact")

    evidence = result.attributions[0].api_evidence[0]
    assert evidence.kind is ApiEvidenceKind.API_INSPECTION_UNAVAILABLE
    assert evidence.old_class_present is True
    assert evidence.new_class_present is None
    assert all(item.kind is not ApiEvidenceKind.REMOVED_CLASS for item in result.attributions[0].api_evidence)
