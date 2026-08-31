"""Prepare 20 frozen-candidate Java/Maven repositories for BUMP-FINAL-v1."""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from bumpshield.execution.command_runner import CommandRunner


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmark"
DEFAULT_RUNTIME = BENCHMARK / "final-runtime"
DEFAULT_CASES = BENCHMARK / "final-cases"
GROUP = "com.bumpshield.finalfixture"


@dataclass(frozen=True, slots=True)
class Scenario:
    number: int
    case_type: str
    failure_kind: str
    concept: str
    old_method: str
    new_method: str
    operation: str
    inputs: tuple[str, ...]
    multi_call: bool

    @property
    def case_id(self) -> str:
        return f"final-case-{self.number:03d}"

    @property
    def namespace(self) -> str:
        return f"c{self.number:03d}"

    @property
    def target_artifact(self) -> str:
        suffix = "api" if self.case_type == "DIRECT" else "core"
        return f"{self.namespace}-{suffix}"

    @property
    def breaking_artifact(self) -> str:
        return (
            self.target_artifact
            if self.case_type == "DIRECT"
            else f"{self.namespace}-legacy-api"
        )


SCENARIOS = (
    Scenario(1, "DIRECT", "REMOVED_METHOD", "TextCleaner", "cleanLegacy", "clean", "trim", ("  alpha  ", " beta", "   "), True),
    Scenario(2, "DIRECT", "REMOVED_METHOD", "NameCanonicalizer", "canonicalName", "canonicalize", "upper", ("Ada", "grace", "Turing"), False),
    Scenario(3, "DIRECT", "REMOVED_METHOD", "TokenMirror", "mirrorToken", "mirror", "reverse", ("abc", "racecar", "xy"), True),
    Scenario(4, "DIRECT", "CHANGED_METHOD_SIGNATURE", "WhitespaceFolder", "fold", "fold", "collapse", ("a   b", "  c d  ", "one"), False),
    Scenario(5, "DIRECT", "CHANGED_METHOD_SIGNATURE", "LabelWrapper", "wrap", "wrap", "wrap", ("red", " blue ", "x"), True),
    Scenario(6, "DIRECT", "CHANGED_METHOD_SIGNATURE", "KeyCompactor", "compact", "compact", "strip_dash", ("a-b-c", "plain", "x-y"), False),
    Scenario(7, "DIRECT", "REMOVED_CLASS", "LegacyCaseMap", "mapCase", "convert", "lower", ("ABC", "MiXeD", "z"), True),
    Scenario(8, "DIRECT", "REMOVED_CLASS", "LegacyIdentifier", "identifier", "create", "prefix", (" 42 ", "abc", "z9"), False),
    Scenario(9, "DIRECT", "REMOVED_PACKAGE", "StatusDecorator", "decorate", "decorate", "suffix", ("ready", " done ", "x"), True),
    Scenario(10, "DIRECT", "REMOVED_PACKAGE", "WordSeparator", "separate", "separate", "underscore", ("a_b", "plain", "x_y_z"), False),
    Scenario(11, "TRANSITIVE", "REMOVED_METHOD", "RecordTrimmer", "trimRecord", "normalize", "trim", (" item ", "two", "   "), True),
    Scenario(12, "TRANSITIVE", "CHANGED_METHOD_SIGNATURE", "SequenceReverser", "reverse", "reverse", "reverse", ("123", "abcd", "q"), False),
    Scenario(13, "TRANSITIVE", "REMOVED_CLASS", "LegacyHeader", "header", "render", "upper", ("accept", "host", "x-id"), True),
    Scenario(14, "TRANSITIVE", "REMOVED_CLASS", "LegacySentence", "sentence", "normalize", "collapse", ("hello   world", " one two ", "x"), False),
    Scenario(15, "TRANSITIVE", "REMOVED_PACKAGE", "Envelope", "enclose", "enclose", "wrap", ("note", " x ", "data"), True),
    Scenario(16, "TRANSITIVE", "REMOVED_PACKAGE", "LocaleLabel", "label", "label", "lower", ("EN_US", "Mixed", "A"), False),
    Scenario(17, "TRANSITIVE", "REMOVED_DEPENDENCY", "LegacyCode", "code", "create", "prefix", (" 7 ", "xyz", "0"), True),
    Scenario(18, "TRANSITIVE", "REMOVED_DEPENDENCY", "LegacyResult", "result", "finish", "suffix", ("pass", "ok", "value"), False),
    Scenario(19, "TRANSITIVE", "REMOVED_DEPENDENCY", "LegacyPath", "path", "compact", "strip_dash", ("a-b", "root-node", "plain"), True),
    Scenario(20, "TRANSITIVE", "REMOVED_DEPENDENCY", "LegacyPayload", "payload", "normalize", "trim", (" payload ", "data", "  x"), False),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maven", default="mvn", help="Maven executable")
    parser.add_argument("--maven-repository", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASES)
    arguments = parser.parse_args()
    runtime = arguments.runtime_dir.expanduser().resolve()
    case_dir = arguments.case_dir.expanduser().resolve()
    _require_owned_path(runtime, DEFAULT_RUNTIME, "runtime")
    _require_owned_path(case_dir, DEFAULT_CASES, "case manifest")
    repository = arguments.maven_repository.expanduser().resolve()
    repository.mkdir(parents=True, exist_ok=True)
    runner = CommandRunner(default_timeout=600)

    _replace_directory(runtime)
    _replace_directory(case_dir)
    references: list[str] = []
    for scenario in SCENARIOS:
        base_sha, updated_sha = _prepare_case(
            runner, scenario, runtime, arguments.maven, repository
        )
        manifest = _manifest(scenario, base_sha, updated_sha)
        manifest_path = case_dir / f"{scenario.case_id}.json"
        _write_json(manifest_path, manifest)
        references.append(f"final-cases/{manifest_path.name}")
        print(f"prepared {scenario.case_id}: {base_sha[:10]}..{updated_sha[:10]}")

    suite = {
        "id": "BUMP-FINAL-v1",
        "cases": references,
        "strategies": ["direct-one-shot", "direct-retry", "bumpshield"],
        "trials": 1,
        "evaluation_config": "final-config-v1.json",
        "dataset_lock": "bump-final-v1.lock.json",
    }
    _write_json(BENCHMARK / "bump-final-v1.json", suite)
    print(f"suite: {BENCHMARK / 'bump-final-v1.json'}")
    print(f"Maven repository: {repository}")
    return 0


def _prepare_case(
    runner: CommandRunner,
    scenario: Scenario,
    runtime: Path,
    maven: str,
    maven_repository: Path,
) -> tuple[str, str]:
    case_root = runtime / scenario.case_id
    libraries = case_root / "libraries"
    old_package = f"{GROUP}.{scenario.namespace}.legacy"
    new_package = (
        f"{GROUP}.{scenario.namespace}.modern"
        if scenario.failure_kind in {"REMOVED_PACKAGE", "REMOVED_DEPENDENCY"}
        else old_package
    )
    old_class = scenario.concept
    new_class = (
        scenario.concept.removeprefix("Legacy") + "V2"
        if scenario.failure_kind in {"REMOVED_CLASS", "REMOVED_DEPENDENCY"}
        else old_class
    )

    old_artifact = scenario.breaking_artifact
    new_artifact = (
        f"{scenario.namespace}-replacement-api"
        if scenario.failure_kind == "REMOVED_DEPENDENCY"
        else old_artifact
    )
    old_library = libraries / f"{old_artifact}-1"
    new_library = libraries / f"{new_artifact}-2"
    _write_library(
        old_library,
        old_artifact,
        "1.0.0",
        old_package,
        old_class,
        scenario.old_method,
        scenario.operation,
        with_options=False,
    )
    _write_library(
        new_library,
        new_artifact,
        "2.0.0",
        new_package,
        new_class,
        scenario.new_method,
        scenario.operation,
        with_options=scenario.failure_kind not in {"REMOVED_PACKAGE"},
    )
    _install(runner, old_library, maven, maven_repository)
    _install(runner, new_library, maven, maven_repository)

    if scenario.case_type == "TRANSITIVE":
        target_old = libraries / f"{scenario.target_artifact}-1"
        target_new = libraries / f"{scenario.target_artifact}-2"
        _write_target_library(
            target_old,
            scenario,
            "1.0.0",
            old_artifact,
            "1.0.0",
        )
        _write_target_library(
            target_new,
            scenario,
            "2.0.0",
            new_artifact,
            "2.0.0",
        )
        _install(runner, target_old, maven, maven_repository)
        _install(runner, target_new, maven, maven_repository)

    application = case_root / "application"
    _write_application(application, scenario, old_package, old_class)
    updated_pom = _application_pom(scenario, "2.0.0")
    base_sha, updated_sha = _git_revisions(runner, application, updated_pom)
    _validate_application(runner, application, maven, maven_repository)
    return base_sha, updated_sha


def _write_library(
    root: Path,
    artifact: str,
    version: str,
    package: str,
    class_name: str,
    method: str,
    operation: str,
    *,
    with_options: bool,
) -> None:
    _write(root / "pom.xml", _library_pom(artifact, version))
    source = root / "src/main/java" / Path(*package.split("."))
    options_parameter = ", MigrationOptions options" if with_options else ""
    options_check = (
        '        if (options == null) { throw new IllegalArgumentException("options"); }\n'
        if with_options
        else ""
    )
    imports = "import java.util.Locale;\n\n" if operation in {"upper", "lower"} else ""
    java = (
        f"package {package};\n\n{imports}"
        f"public final class {class_name} {{\n"
        f"    public String {method}(String value{options_parameter}) {{\n"
        f"{options_check}        return {_java_expression(operation)};\n"
        "    }\n"
        "}\n"
    )
    _write(source / f"{class_name}.java", java)
    if with_options:
        _write(
            source / "MigrationOptions.java",
            (
                f"package {package};\n\n"
                "public final class MigrationOptions {\n"
                "    public static final MigrationOptions DEFAULT = new MigrationOptions();\n"
                "    private MigrationOptions() {}\n"
                "}\n"
            ),
        )


def _write_target_library(
    root: Path,
    scenario: Scenario,
    version: str,
    dependency_artifact: str,
    dependency_version: str,
) -> None:
    dependency = (
        "    <dependency>\n"
        f"      <groupId>{GROUP}</groupId>\n"
        f"      <artifactId>{dependency_artifact}</artifactId>\n"
        f"      <version>{dependency_version}</version>\n"
        "    </dependency>\n"
    )
    _write(
        root / "pom.xml",
        _library_pom(scenario.target_artifact, version, dependency),
    )
    package = f"{GROUP}.{scenario.namespace}.core"
    _write(
        root / "src/main/java" / Path(*package.split(".")) / "CoreMarker.java",
        f"package {package};\n\npublic final class CoreMarker {{ private CoreMarker() {{}} }}\n",
    )


def _write_application(
    root: Path, scenario: Scenario, old_package: str, old_class: str
) -> None:
    _write(root / "pom.xml", _application_pom(scenario, "1.0.0"))
    package = f"{GROUP}.{scenario.namespace}.app"
    class_name = f"MigrationClient{scenario.number:03d}"
    field = old_class[0].lower() + old_class[1:]
    pair = (
        f"\n    public String pair(String left, String right) {{\n"
        f"        return {field}.{scenario.old_method}(left) + \"|\" + {field}.{scenario.old_method}(right);\n"
        "    }\n"
        if scenario.multi_call
        else ""
    )
    app = (
        f"package {package};\n\n"
        f"import {old_package}.{old_class};\n\n"
        f"public final class {class_name} {{\n"
        f"    private final {old_class} {field} = new {old_class}();\n\n"
        "    public String transform(String value) {\n"
        f"        return {field}.{scenario.old_method}(value);\n"
        f"    }}\n{pair}"
        "}\n"
    )
    source = root / "src/main/java" / Path(*package.split("."))
    _write(source / f"{class_name}.java", app)
    test = _test_source(scenario, package, class_name)
    test_root = root / "src/test/java" / Path(*package.split("."))
    _write(test_root / f"{class_name}Test.java", test)


def _test_source(scenario: Scenario, package: str, class_name: str) -> str:
    assertions = []
    for value in scenario.inputs:
        expected = _python_transform(scenario.operation, value)
        assertions.append(
            f"        assertEquals({_java_string(expected)}, client.transform({_java_string(value)}));"
        )
    if scenario.multi_call:
        left, right = scenario.inputs[:2]
        expected = f"{_python_transform(scenario.operation, left)}|{_python_transform(scenario.operation, right)}"
        assertions.append(
            f"        assertEquals({_java_string(expected)}, client.pair({_java_string(left)}, {_java_string(right)}));"
        )
    return (
        f"package {package};\n\n"
        "import static org.junit.jupiter.api.Assertions.assertEquals;\n"
        "import org.junit.jupiter.api.Test;\n\n"
        f"class {class_name}Test {{\n"
        "    @Test\n"
        "    void preservesLegacyBehavior() {\n"
        f"        {class_name} client = new {class_name}();\n"
        + "\n".join(assertions)
        + "\n    }\n}\n"
    )


def _git_revisions(
    runner: CommandRunner, application: Path, updated_pom: str
) -> tuple[str, str]:
    _run(runner, application, "git", "init", "--quiet")
    _run(runner, application, "git", "config", "user.name", "BumpShield Final Benchmark")
    _run(runner, application, "git", "config", "user.email", "final@example.invalid")
    _run(runner, application, "git", "add", ".")
    _run(runner, application, "git", "commit", "--quiet", "-m", "working dependency")
    base = _output(runner, application, "git", "rev-parse", "HEAD")
    _write(application / "pom.xml", updated_pom)
    _run(runner, application, "git", "add", "pom.xml")
    _run(runner, application, "git", "commit", "--quiet", "-m", "breaking dependency upgrade")
    updated = _output(runner, application, "git", "rev-parse", "HEAD")
    return base, updated


def _validate_application(
    runner: CommandRunner, application: Path, maven: str, repository: Path
) -> None:
    updated = _output(runner, application, "git", "rev-parse", "HEAD")
    _run(runner, application, "git", "switch", "--quiet", "--detach", "HEAD^")
    base = runner.run(
        (maven, "-B", f"-Dmaven.repo.local={repository}", "test"),
        cwd=application,
        timeout=600,
    )
    _run(runner, application, "git", "switch", "--quiet", "--detach", updated)
    changed = _output(runner, application, "git", "diff", "--name-only", "HEAD^")
    if base.exit_code != 0 or base.timed_out:
        raise RuntimeError(f"base Maven test failed: {application}")
    updated_result = runner.run(
        (maven, "-B", f"-Dmaven.repo.local={repository}", "test"),
        cwd=application,
        timeout=600,
    )
    if updated_result.exit_code == 0 or updated_result.timed_out:
        raise RuntimeError(f"updated Maven test did not fail: {application}")
    if changed.strip() != "pom.xml":
        raise RuntimeError(f"updated commit changes more than pom.xml: {application}")


def _manifest(scenario: Scenario, base: str, updated: str) -> dict[str, object]:
    old_package = f"{GROUP}.{scenario.namespace}.legacy"
    old_class = scenario.concept
    new_breaking_version = (
        "REMOVED" if scenario.failure_kind == "REMOVED_DEPENDENCY" else "2.0.0"
    )
    return {
        "id": scenario.case_id,
        "description": f"Controlled {scenario.case_type.lower()} {scenario.failure_kind.lower().replace('_', ' ')} migration",
        "task": {
            "repository": f"../final-runtime/{scenario.case_id}/application",
            "base_commit": base,
            "updated_commit": updated,
            "target_dependency": {
                "group_id": GROUP,
                "artifact_id": scenario.target_artifact,
                "old_version": "1.0.0",
                "new_version": "2.0.0",
            },
        },
        "case_type": scenario.case_type,
        "source": "SYNTHETIC_FIXTURE",
        "split": "FINAL",
        "ground_truth": {
            "breaking_dependency": {
                "group_id": GROUP,
                "artifact_id": scenario.breaking_artifact,
                "old_version": "1.0.0",
                "new_version": new_breaking_version,
            },
            "failure_kind": scenario.failure_kind,
            "class": f"{old_package}.{old_class}",
            "member": (
                f"{scenario.old_method}(java.lang.String)"
                if scenario.failure_kind in {"REMOVED_METHOD", "CHANGED_METHOD_SIGNATURE"}
                else None
            ),
        },
        "provenance": {
            "project_name": scenario.case_id,
            "repository_url": None,
            "source_commit": None,
            "license": None,
            "upgrade_origin": "CONSTRUCTED",
            "ground_truth_basis": "Controlled old/new source, Maven dependency tree, compiler diagnostic, and javap comparison.",
        },
        "tags": [
            scenario.case_type.lower(),
            scenario.failure_kind.lower().replace("_", "-"),
            "synthetic",
            "constructed-upgrade",
        ],
    }


def _library_pom(artifact: str, version: str, dependencies: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        f"  <groupId>{GROUP}</groupId>\n"
        f"  <artifactId>{artifact}</artifactId>\n"
        f"  <version>{version}</version>\n"
        "  <properties><maven.compiler.release>17</maven.compiler.release><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>\n"
        + (f"  <dependencies>\n{dependencies}  </dependencies>\n" if dependencies else "")
        + "</project>\n"
    )


def _application_pom(scenario: Scenario, version: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        f"  <groupId>{GROUP}</groupId><artifactId>{scenario.namespace}-application</artifactId><version>1.0.0</version>\n"
        "  <properties><maven.compiler.release>17</maven.compiler.release><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding></properties>\n"
        "  <dependencies>\n"
        f"    <dependency><groupId>{GROUP}</groupId><artifactId>{scenario.target_artifact}</artifactId><version>{version}</version></dependency>\n"
        "    <dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>5.10.2</version><scope>test</scope></dependency>\n"
        "  </dependencies>\n"
        "  <build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.2.5</version></plugin></plugins></build>\n"
        "</project>\n"
    )


def _java_expression(operation: str) -> str:
    return {
        "trim": "value.trim()",
        "upper": "value.toUpperCase(Locale.ROOT)",
        "reverse": "new StringBuilder(value).reverse().toString()",
        "collapse": 'value.trim().replaceAll("\\\\s+", " ")',
        "wrap": '"[" + value.trim() + "]"',
        "strip_dash": 'value.replace("-", "")',
        "lower": "value.toLowerCase(Locale.ROOT)",
        "prefix": '"id-" + value.trim()',
        "suffix": 'value.trim() + "-ok"',
        "underscore": "value.replace('_', ' ')",
    }[operation]


def _python_transform(operation: str, value: str) -> str:
    if operation == "trim":
        return value.strip()
    if operation == "upper":
        return value.upper()
    if operation == "reverse":
        return value[::-1]
    if operation == "collapse":
        return " ".join(value.split())
    if operation == "wrap":
        return f"[{value.strip()}]"
    if operation == "strip_dash":
        return value.replace("-", "")
    if operation == "lower":
        return value.lower()
    if operation == "prefix":
        return "id-" + value.strip()
    if operation == "suffix":
        return value.strip() + "-ok"
    if operation == "underscore":
        return value.replace("_", " ")
    raise ValueError(operation)


def _install(
    runner: CommandRunner, root: Path, maven: str, repository: Path
) -> None:
    _run(
        runner,
        root,
        maven,
        "-B",
        f"-Dmaven.repo.local={repository}",
        "-DskipTests",
        "install",
    )


def _output(runner: CommandRunner, cwd: Path, *command: str) -> str:
    result = runner.run(command, cwd=cwd, timeout=600)
    if result.exit_code != 0 or result.timed_out:
        raise RuntimeError(f"command failed in {cwd}: {' '.join(command)}")
    return result.stdout.strip()


def _run(runner: CommandRunner, cwd: Path, *command: str) -> None:
    result = runner.run(command, cwd=cwd, timeout=600)
    if result.exit_code != 0 or result.timed_out:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"command failed in {cwd}: {' '.join(command)}: {detail[-1200:]}")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _java_string(value: str) -> str:
    return json.dumps(value)


def _replace_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def _require_owned_path(path: Path, expected: Path, label: str) -> None:
    if path != expected.resolve():
        raise ValueError(f"{label} directory must be {expected.resolve()}")


if __name__ == "__main__":
    raise SystemExit(main())
