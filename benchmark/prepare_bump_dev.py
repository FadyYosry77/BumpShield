"""Materialize BUMP-DEV Git repositories and install their tiny Maven libraries."""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path

from bumpshield.execution.command_runner import CommandRunner


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmark"
DEFAULT_RUNTIME = BENCHMARK / "runtime"


@dataclass(frozen=True, slots=True)
class FixtureCase:
    id: str
    application: Path


CASES = (
    FixtureCase(
        "direct-removed-method",
        BENCHMARK / "fixtures/direct-removed-method/application",
    ),
    FixtureCase(
        "transitive-removed-method",
        ROOT / "integration-fixtures/phase7_1/application",
    ),
    FixtureCase(
        "direct-changed-signature",
        BENCHMARK / "fixtures/direct-changed-signature/application",
    ),
    FixtureCase(
        "transitive-removed-class",
        BENCHMARK / "fixtures/transitive-removed-class/application",
    ),
)

LIBRARIES = (
    ROOT / "integration-fixtures/phase7_1/parser-lib-old",
    ROOT / "integration-fixtures/phase7_1/parser-lib-new",
    ROOT / "integration-fixtures/phase7_1/core-lib-old",
    ROOT / "integration-fixtures/phase7_1/core-lib-new",
    BENCHMARK / "fixtures/direct-changed-signature/renderer-lib-old",
    BENCHMARK / "fixtures/direct-changed-signature/renderer-lib-new",
    BENCHMARK / "fixtures/transitive-removed-class/format-lib-old",
    BENCHMARK / "fixtures/transitive-removed-class/format-lib-new",
    BENCHMARK / "fixtures/transitive-removed-class/facade-lib-old",
    BENCHMARK / "fixtures/transitive-removed-class/facade-lib-new",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maven", default="mvn", help="Maven executable")
    parser.add_argument(
        "--maven-repository",
        type=Path,
        required=True,
        help="disposable Maven local repository shared with the benchmark run",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME,
        help="generated fixture repository root",
    )
    arguments = parser.parse_args()
    runtime = arguments.runtime_dir.expanduser().resolve()
    _require_safe_runtime(runtime)
    repository = arguments.maven_repository.expanduser().resolve()
    repository.mkdir(parents=True, exist_ok=True)
    runner = CommandRunner(default_timeout=600)

    for library in LIBRARIES:
        _run(
            runner,
            library,
            arguments.maven,
            "-B",
            f"-Dmaven.repo.local={repository}",
            "-DskipTests",
            "install",
        )

    for case in CASES:
        destination = runtime / case.id / "application"
        if destination.parent.exists():
            shutil.rmtree(destination.parent)
        destination.parent.mkdir(parents=True)
        shutil.copytree(case.application, destination)
        updated_path = destination / "pom.updated.xml"
        updated_pom = updated_path.read_text(encoding="utf-8")
        updated_path.unlink()
        _git(runner, destination, "init", "--quiet")
        _git(runner, destination, "config", "user.name", "BumpShield Benchmark")
        _git(
            runner,
            destination,
            "config",
            "user.email",
            "benchmark@example.invalid",
        )
        _git(runner, destination, "add", ".")
        _git(runner, destination, "commit", "--quiet", "-m", "working dependency")
        _git(runner, destination, "tag", "base")
        (destination / "pom.xml").write_text(updated_pom, encoding="utf-8")
        _git(runner, destination, "add", "pom.xml")
        _git(runner, destination, "commit", "--quiet", "-m", "breaking upgrade")
        _git(runner, destination, "tag", "updated")
        _validate_case(
            runner,
            destination,
            arguments.maven,
            repository,
        )
        print(f"prepared {case.id}: {destination}")

    print(f"Maven repository: {repository}")
    print(
        "Run with MAVEN_OPTS="
        f"-Dmaven.repo.local={repository} so BumpShield sees the same artifacts."
    )
    return 0


def _validate_case(
    runner: CommandRunner,
    repository: Path,
    maven: str,
    maven_repository: Path,
) -> None:
    _git(runner, repository, "switch", "--quiet", "--detach", "base")
    base = runner.run(
        (
            maven,
            "-B",
            f"-Dmaven.repo.local={maven_repository}",
            "test",
        ),
        cwd=repository,
        timeout=600,
    )
    _git(runner, repository, "switch", "--quiet", "master")
    updated = runner.run(
        (
            maven,
            "-B",
            f"-Dmaven.repo.local={maven_repository}",
            "test",
        ),
        cwd=repository,
        timeout=600,
    )
    if base.exit_code != 0 or base.timed_out:
        raise RuntimeError(f"fixture base did not pass: {repository}")
    if updated.exit_code == 0 or updated.timed_out:
        raise RuntimeError(f"fixture updated revision did not fail: {repository}")


def _require_safe_runtime(runtime: Path) -> None:
    benchmark = BENCHMARK.resolve()
    try:
        runtime.relative_to(benchmark)
    except ValueError as error:
        raise ValueError("runtime directory must stay inside benchmark/") from error
    if runtime == benchmark or runtime.name != "runtime":
        raise ValueError("runtime directory must be the benchmark/runtime directory")
    runtime.mkdir(parents=True, exist_ok=True)


def _git(runner: CommandRunner, cwd: Path, *arguments: str) -> None:
    _run(runner, cwd, "git", *arguments)


def _run(runner: CommandRunner, cwd: Path, *command: str) -> None:
    result = runner.run(command, cwd=cwd, timeout=600)
    if result.timed_out or result.exit_code != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"command failed in {cwd}: {' '.join(command)}: {detail}")


if __name__ == "__main__":
    raise SystemExit(main())
