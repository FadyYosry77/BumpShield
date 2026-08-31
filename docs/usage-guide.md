# BumpShield Usage Guide

This guide covers both supported ways to use BumpShield:

1. the command-line interface for real Java/Maven dependency migrations;
2. the Streamlit GUI for offline recorded replay or an explicitly started live run.

It also explains how to validate the installation, inspect artifacts, and use
the BoneCP real-world showcase without rerunning the frozen benchmark.

## 1. What BumpShield Does

BumpShield investigates a Java/Maven project that worked at one Git commit and
failed after a dependency upgrade at another commit. Its pipeline is:

```text
Reproduce
→ Dependency Diff
→ Failure Localization
→ API Evidence
→ Causal Diagnosis
→ Migration Plan
→ Constrained Repair
→ Independent Verification
```

Codex proposes source edits only during repair. Git, Maven, dependency guards,
test-integrity checks, patch analysis, and the independent verifier decide
whether the result can be called `VERIFIED_MIGRATION`.

BumpShield does not apply the final patch to the original repository. Repair
occurs in a disposable Git worktree, and a successful patch is exported to the
external state directory.

## 2. Requirements

### Offline replay and deterministic tests

- Python 3.11 or newer
- Git
- Streamlit only when using the GUI

Recorded replay does not require Java, Maven, Codex, provider quota, or network
access.

### Live investigation and repair

- Python 3.11 or newer
- Git
- a JDK that provides `java` and `javap`
- Maven, or a working Maven wrapper in the target project
- Codex CLI authenticated and available for the repair stage

The target project must use Java source and Maven. The current BumpShield v1
scope does not cover Gradle, Bazel, Ant, Kotlin, or Scala migrations.

## 3. Safe Installation

Run these commands from the BumpShield repository root:

```bash
cd /path/to/BumpShield
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,demo]'
```

Using a virtual environment avoids Debian/Ubuntu's `externally-managed-
environment` restriction and keeps project packages isolated from system
Python.

Confirm the installation:

```bash
bumpshield version
bumpshield --help
python -c "import bumpshield, demo_ui; print('imports: PASS')"
```

When returning to the project later, reactivate the environment:

```bash
cd /path/to/BumpShield
source .venv/bin/activate
```

## 4. Verify the Local Installation

Run the deterministic suite:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider
```

The Phase 13 repository state contains 276 deterministic tests. The suite does
not execute the provider-backed final benchmark.

Verify the frozen evaluation files without executing any benchmark trial:

```bash
python -m bumpshield.cli benchmark \
  benchmark/bump-final-v1.json \
  --verify-freeze
```

Expected frozen values:

```text
Configuration: 3c0dfaad58f985d1c9a9db7f17ee28a84af7f8b3bcce45de5dd078877943ff56
Dataset: 8bd13704194037bd3c672233af5d4e1102d78cb084aea736dd7738ded37a4e8a
Result: VALID
```

Do not run `BUMP-FINAL-v1` again. It is the preserved final evaluation record.

## 5. Prepare a Migration Task

BumpShield requires one Git repository with two commits:

- `base_commit`: the project builds and tests successfully;
- `updated_commit`: the dependency is upgraded and the build fails because of
  that migration.

The updated commit must already contain the dependency-version change. Keep
the working tree clean before beginning.

Create a task file such as `task.json`:

```json
{
  "repository": "/absolute/path/to/java-project",
  "base_commit": "<passing-commit-sha>",
  "updated_commit": "<failing-upgrade-commit-sha>",
  "target_dependency": {
    "group_id": "org.example",
    "artifact_id": "example-library",
    "old_version": "1.0.0",
    "new_version": "2.0.0"
  }
}
```

`repository` may also be relative to the task file. Both commit identifiers
must resolve in that repository.

Before using BumpShield, manually confirm the basic premise:

```bash
git -C /absolute/path/to/java-project status --short
git -C /absolute/path/to/java-project rev-parse <passing-commit-sha>
git -C /absolute/path/to/java-project rev-parse <failing-upgrade-commit-sha>
```

Use an external state directory rather than writing runtime artifacts into the
target project:

```bash
export BUMPSHIELD_STATE="/tmp/bumpshield-local-state"
```

For a controlled Maven cache, set:

```bash
export MAVEN_OPTS="-Dmaven.repo.local=/tmp/bumpshield-local-m2"
```

## 6. CLI Usage

All examples below assume the virtual environment is active and `task.json`
is in the current directory.

### 6.1 Reproduce the regression

```bash
bumpshield reproduce task.json --state-dir "$BUMPSHIELD_STATE"
```

Required successful investigation outcome:

```text
base: PASS
updated: FAIL
regression: CONFIRMED
```

If the base fails, stop and repair the fixture or environment. BumpShield
cannot defend a migration result without a passing base revision.

### 6.2 Compare dependency resolution

```bash
bumpshield dependencies task.json --state-dir "$BUMPSHIELD_STATE"
```

This compares Maven's resolved dependency graphs at both commits. It checks
that the requested target moved from the declared old version to the declared
new version and records direct and transitive changes.

### 6.3 Parse and localize failures

```bash
bumpshield failures task.json --state-dir "$BUMPSHIELD_STATE"
```

The result identifies supported compiler or test failures and maps them to
bounded Java source context. Typical categories include missing methods,
classes, packages, or changed signatures.

### 6.4 Collect API evidence

```bash
bumpshield evidence task.json --state-dir "$BUMPSHIELD_STATE"
```

BumpShield attributes the failing class to resolved JARs and compares old and
new public APIs with `javap`. Candidate APIs remain evidence; they are not
treated as verified repairs.

### 6.5 Build the causal diagnosis

```bash
bumpshield diagnose task.json --state-dir "$BUMPSHIELD_STATE"
```

Useful statuses are:

- `SUPPORTED_DIAGNOSIS`: evidence supports a causal explanation;
- `PARTIAL` or `AMBIGUOUS`: some evidence exists but is not conclusive;
- `INSUFFICIENT`: no defensible automated diagnosis is available.

The evidence score is deterministic and ordinal. It is not a probability.

### 6.6 Create the bounded migration plan

```bash
bumpshield plan task.json --state-dir "$BUMPSHIELD_STATE"
```

`PLAN_READY` records the allowed files, protected files, required outcome,
repair constraints, and verification requirements. A plan does not mean that
a repair has succeeded.

### 6.7 Run repair and independent verification

```bash
bumpshield repair task.json --state-dir "$BUMPSHIELD_STATE"
```

`repair` runs the complete pipeline internally, so running the earlier stage
commands first is optional. They are useful when presenting or diagnosing the
investigation one stage at a time.

During repair:

1. Codex receives bounded source context and constraints.
2. Codex edits an isolated worktree.
3. BumpShield reads the actual Git diff.
4. Dependency guards ensure upgraded versions remain.
5. Maven compile and tests execute independently.
6. Test deletion, disablement, and skipping checks execute.
7. Patch scope and safety checks execute.
8. Only the independent verifier can emit `VERIFIED_MIGRATION`.

Typical successful output:

```text
Attempt 1: VERIFIED
Compile: PASS
Tests: PASS
FINAL STATUS: VERIFIED_MIGRATION
```

Provider quota, authentication, timeout, or service failures are operational
failures. Do not manually accept an unverified patch merely because it looks
correct.

### 6.8 Run without installing the console script

Every CLI command also works through Python:

```bash
python -m bumpshield.cli reproduce task.json --state-dir "$BUMPSHIELD_STATE"
python -m bumpshield.cli repair task.json --state-dir "$BUMPSHIELD_STATE"
```

## 7. Inspect CLI Artifacts

Each command prints a run identifier and artifact directory. Common artifacts
include:

```text
reproduction.json
dependency-diff.json
failures.json
api-evidence.json
causal-diagnosis.json
migration-plan.json
attempts/<number>/patch.diff
attempts/<number>/verification.json
final.patch
repair-result.json
migration-report.txt
```

Inspect structured results with `jq`:

```bash
jq . "$BUMPSHIELD_STATE/runs/<run-id>/causal-diagnosis.json"
jq . "$BUMPSHIELD_STATE/runs/<run-id>/migration-plan.json"
jq . "$BUMPSHIELD_STATE/runs/<run-id>/verification.json"
less "$BUMPSHIELD_STATE/runs/<run-id>/final.patch"
```

`final.patch` is generated from Git ground truth. Apply it to your own branch
only after review:

```bash
git -C /absolute/path/to/java-project apply --check \
  "$BUMPSHIELD_STATE/runs/<run-id>/final.patch"
```

The check command does not modify the repository. Applying, committing, and
pushing remain deliberate user actions outside BumpShield.

## 8. Offline BoneCP Showcase from the CLI

The Phase 13 BoneCP bundle is a recorded real-world run over genuine
open-source source. The Guava `15.0` to `21.0` migration was constructed for
the showcase; it is not an upstream historical regression and is not part of
`BUMP-FINAL-v1`.

Validate it without GUI or external tools:

```bash
python - <<'PY'
from demo_ui.replay import REAL_WORLD_REPLAY_BUNDLE, RecordedRunSource

source = RecordedRunSource.load(REAL_WORLD_REPLAY_BUNDLE)
bundle = source.bundle

print("Mode:", source.mode_label)
print("Project:", bundle.provenance.project)
print("Upgrade:", bundle.investigation.requested)
print("Compile:", bundle.compile.status)
print("Tests:", bundle.tests.status, bundle.tests.tests)
print("Result:", bundle.verification.final_status)
print("Bundle hash:", bundle.bundle_hash)
PY
```

Expected core result:

```text
Mode: RECORDED REAL-WORLD VERIFIED RUN
Project: BoneCP
Compile: PASS
Tests: PASS 197
Result: VERIFIED_MIGRATION
```

Run its integrity tests:

```bash
python -m pytest -p no:cacheprovider tests/test_demo_ui_replay.py
```

Inspect the compact evidence snapshot:

```bash
jq . showcase/real-world/provenance.json
jq . showcase/real-world/results/reproduction.json
jq . showcase/real-world/results/failure-summary.json
jq . showcase/real-world/results/verification.json
less showcase/real-world/results/final.patch
```

The replay makes zero Codex, Maven, Java, Git-worktree, benchmark, and network
calls.

## 9. GUI Usage

Launch the GUI from the repository root with the virtual environment active:

```bash
cd /path/to/BumpShield
source .venv/bin/activate
python -m streamlit run demo_ui/app.py
```

Open:

```text
http://localhost:8501
```

If another application uses port 8501:

```bash
python -m streamlit run demo_ui/app.py --server.port 8502
```

### 9.1 Recorded Verified Run

Recorded mode is the safe default for demonstrations. It validates the bundle
manifest and SHA-256 hashes before showing any verified result.

Available scenarios:

- **Synthetic Transitive Demo**: shows a transitive dependency API break;
- **BoneCP Real-World Showcase**: shows the genuine open-source BoneCP source
  with the constructed Guava upgrade.

Recommended BoneCP walkthrough:

1. Keep **Recorded Verified Run** selected in the sidebar.
2. Choose **BoneCP Real-World Showcase** in the replay selector.
3. Confirm the `RECORDED REAL-WORLD VERIFIED RUN` label.
4. Click **Start Replay** for the ten-stage walkthrough, or
   **30-Second Fast View** for the compact presentation.
5. Show the base PASS and updated FAIL evidence.
6. Show Guava `15.0` to `21.0` as the direct causal change.
7. Show both localized `Objects.toStringHelper(...)` failures.
8. Show `REMOVED_MEMBER` API evidence and the 100/100 deterministic score.
9. Show the two-file `MoreObjects.toStringHelper(...)` Git patch.
10. Finish on the 197-test PASS and independent `VERIFIED_MIGRATION` result.

Replay does not claim that a new repair is running. It remains visibly labeled
as recorded evidence.

### 9.2 Live Run

Live mode uses the actual BumpShield services and therefore requires Git,
Java, Maven, the target repository, and Codex for repair.

1. Select **Live Run** in the sidebar.
2. Open **New Migration**.
3. Enter the repository, base commit, updated commit, dependency coordinates,
   versions, and external state directory.
4. Click **Investigate Upgrade**. This runs deterministic investigation only;
   it does not call Codex.
5. Review **Investigation** and **Migration Plan**.
6. Open **Repair & Verification**.
7. Click **Repair in Isolated Workspace** only when ready for a provider call.
8. Review the attempt timeline, actual Git patch, compilation, tests, guards,
   and verifier result.
9. Open **Evidence & Results** for the audit trail and frozen research summary.

Streamlit rerenders do not automatically rerun Maven or Codex. Investigation
and repair require separate explicit button actions.

## 10. Result Meanings

### `VERIFIED_MIGRATION`

The target dependency remains upgraded, causal dependency constraints pass,
compilation passes, tests pass and remain active, and patch scope/safety are
acceptable.

### `UNRESOLVED`

No attempt satisfied independent verification. Inspect attempt feedback,
provider status, compile/test output, and verifier reasons.

### `NEEDS_HUMAN_REVIEW`

Evidence or patch safety is insufficient for automatic acceptance. Review the
structured findings and patch manually; do not relabel it as verified.

### Provider failure

Codex quota, authentication, service availability, timeout, or executable
problems prevented a complete provider attempt. This is distinct from a repair
or verification failure.

## 11. Troubleshooting

### `ModuleNotFoundError: No module named 'demo_ui'`

Stop Streamlit with `Ctrl+C`, install the current repository inside the active
virtual environment, and restart:

```bash
cd /path/to/BumpShield
source .venv/bin/activate
python -m pip install -e '.[dev,demo]'
python -m streamlit run demo_ui/app.py
```

Temporary fallback when Streamlit is already installed:

```bash
cd /path/to/BumpShield
PYTHONPATH="$PWD" streamlit run demo_ui/app.py
```

### `externally-managed-environment`

Do not use `--break-system-packages`. Create and activate `.venv` as shown in
the installation section.

### `streamlit: command not found`

Activate `.venv`, then install the demo extra:

```bash
source .venv/bin/activate
python -m pip install -e '.[demo]'
```

### Maven cannot resolve dependencies

Confirm network availability for the initial download or point `MAVEN_OPTS` at
a pre-populated local repository. Do not treat a repository-resolution outage
as a migration failure.

### Java or `javap` not found

Set `JAVA_HOME` to a JDK, not a JRE, and place `$JAVA_HOME/bin` before other
Java installations on `PATH`:

```bash
export JAVA_HOME="/path/to/jdk"
export PATH="$JAVA_HOME/bin:$PATH"
java -version
javap -version
```

### Codex provider error

Confirm the CLI is installed and authenticated:

```bash
codex --version
```

Quota or service failures should be documented and retried only according to
the applicable evaluation or showcase protocol. Never manually mark an
unverified patch as successful.

### Original repository appears modified

BumpShield should not modify it. Stop and inspect before continuing:

```bash
git -C /absolute/path/to/java-project status --short
git -C /absolute/path/to/java-project worktree list
```

Do not delete or reset user work. Preserve the external state directory and
investigate the unexpected change.

## 12. Safety and Research Integrity

- Never put ground truth into provider prompts.
- Never weaken tests or verifier rules to obtain a green result.
- Never downgrade the target dependency to hide a migration failure.
- Never treat provider prose as verification.
- Review `final.patch` before applying it to another branch.
- Keep runtime state and Maven caches outside source repositories.
- Do not rerun or modify frozen `BUMP-FINAL-v1`.
- Keep the BoneCP constructed showcase separate from benchmark statistics.
- Future algorithm changes belong to a separately versioned BumpShield v2
  evaluation.

## 13. Further Reading

- [Architecture](architecture.md)
- [GUI judge walkthrough](demo.md)
- [BoneCP real-world showcase](real-world-showcase.md)
- [Evaluation protocol](evaluation-protocol.md)
- [Final research results](final-research-results.md)
- [Benchmark documentation](../benchmark/README.md)
