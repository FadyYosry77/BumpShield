# BumpShield judge demo

Always demonstrate Recorded Verified Run first. It gives judges a reliable
2–3 minute walkthrough without depending on provider quota, network access, or
Java/Maven availability. Use Live Run only when the toolchain and Codex
availability have already been confirmed.

## Guaranteed Judge Demo — Recorded Verified Run

Install the optional presentation dependency and launch from the repository
root:

```bash
python -m pip install -e '.[demo]'
streamlit run demo_ui/app.py
```

The GUI defaults to **Recorded Verified Run**. Its portable replay bundle comes
from BUMP-FINAL-v1 case 011, a real BumpShield execution using Git, Maven, Java,
`javap`, Codex, and the independent verifier. The original temporary Phase 7.1
run directory was no longer available, so replay uses this later complete,
preserved, verified transitive removed-method run instead of manufacturing
missing evidence.

The scenario selector also offers **BoneCP Real-World Showcase**, labeled
`RECORDED REAL-WORLD VERIFIED RUN`. It replays a constructed Guava 15-to-21
migration over genuine BoneCP source. Choose it when judges want real-project
evidence; it remains offline and is not part of `BUMP-FINAL-v1` statistics.

Recommended flow:

1. Confirm the visible `RECORDED VERIFIED RUN` and artifact-integrity badge.
2. Click **Start Replay**.
3. Reveal base PASS and updated FAIL.
4. Show requested `c011-core 1.0.0` to `2.0.0` upgrade.
5. Reveal hidden `c011-legacy-api 1.0.0` to `2.0.0` transition.
6. Show localized `trimRecord(java.lang.String)` failure and recorded source.
7. Show old/new `javap` evidence and deterministic 100/100 ordinal score.
8. Show bounded migration plan and real recorded Git patch.
9. Show recorded compile, test, dependency, integrity, and scope checks.
10. Finish on `VERIFIED_MIGRATION` and “The model proposed the patch.
    BumpShield independently verified the migration.”

Use **Previous**, **Next**, **Restart Replay**, and **Show All** to control
pacing. **30-Second Fast View** provides a single-page fallback. Replay performs
no provider, Maven, Java, Git-worktree, benchmark, or network execution.

## Optional Live Demo — 3–5 minutes

This demo uses the controlled transitive fixture from the real Phase 7.1 smoke
test. It is small, fast, and shows the main reason BumpShield exists: the
requested direct dependency is not the artifact that removed the failing API.

## Story

```text
application
└── core-lib 1.0.0 -> 2.0.0        requested upgrade
    └── parser-lib 1.0.0 -> 2.0.0  causal transitive change
        └── Parser.parseValue(String) removed
```

The application still calls `parseValue`. Three JUnit tests require meaningful
whitespace-normalization behavior, so deleting the call or returning a constant
does not satisfy verification.

### Live GUI flow

Select **Live Run** in the sidebar, then use this sequence:

1. Open **Overview**. Establish the message: "You upgraded one dependency, but
   another dependency may own the breaking API."
2. Open **New Migration** and click **Load Demo Fixture**.
3. Confirm the requested `core-lib 1.0.0` to `2.0.0` upgrade.
4. Click **Investigate Upgrade**. This runs deterministic services only; Codex
   is not invoked.
5. Open **Investigation**. Show the hidden `parser-lib` transition, localized
   compiler failure, old/new API evidence, causal chain, and ordinal evidence
   score.
6. Open **Migration Plan**. Show the unverified candidate API, one-file edit
   boundary, and anti-cheating constraints.
7. Open **Repair & Verification**. Emphasize that the original repository will
   not be modified, then click **Repair in Isolated Workspace**.
8. Show the attempt timeline and Git-ground-truth patch.
9. Show compile, tests, dependency guards, test-integrity checks, and patch
   scope from the independent verifier.
10. End on **VERIFIED_MIGRATION** and the statement: "The model proposed the
    migration. BumpShield independently proved it."
11. If time remains, open **Evidence & Results** for artifacts and the honest
    frozen benchmark summary.

Streamlit rerenders do not rerun Maven or Codex; investigation and repair
require separate explicit actions. A provider quota failure offers an explicit
**View Recorded Verified Run** action and never switches modes automatically.
The committed BUMP-FINAL-v1 result snapshot remains read-only; neither mode
executes or mutates that benchmark.

Prepare the fixture before the judge session using the command below. The GUI's
demo shortcut loads its real task values; it does not hardcode an outcome.

## Prerequisites

- BumpShield installed from this repository
- Git, a JDK, and Maven on `PATH`
- Codex CLI logged in for the repair step

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 1. Prepare the fixture

Use disposable Maven and state directories. Preparation installs only the tiny
fixture artifacts, creates ignored Git repositories under `benchmark/runtime/`,
and proves base PASS plus updated FAIL.

```bash
DEMO_ROOT="$(mktemp -d)"
DEMO_M2="$DEMO_ROOT/m2"
DEMO_STATE="$DEMO_ROOT/state"

python3 benchmark/prepare_bump_dev.py \
  --maven mvn \
  --maven-repository "$DEMO_M2"
```

After preparation, either follow the GUI flow above or use the CLI flow below.

Recommended case manifest:

```text
benchmark/cases/transitive-removed-method.json
```

## 2. Show the regression

The generated repository is left at the updated commit. Run its real tests:

```bash
(
  cd benchmark/runtime/transitive-removed-method/application
  mvn -B -Dmaven.repo.local="$DEMO_M2" test
)
```

Expected result: Maven exits nonzero because `Parser.parseValue(String)` no
longer exists. Keep the compiler excerpt visible; avoid scrolling through the
full log.

## 3. Run BumpShield from the CLI

From the BumpShield repository root:

```bash
MAVEN_OPTS="-Dmaven.repo.local=$DEMO_M2" \
  bumpshield repair benchmark/cases/transitive-removed-method.json \
  --state-dir "$DEMO_STATE"
```

`repair` runs the complete pipeline internally. No prior stage command is
required. Depending on provider latency, this is the longest demo step.

Representative milestones:

```text
Regression: CONFIRMED
Dependency change: parser-lib 1.0.0 -> 2.0.0 (TRANSITIVE)
API evidence: REMOVED_MEMBER
Diagnosis: SUPPORTED_DIAGNOSIS / VERY_STRONG
Plan: PLAN_READY / REMOVED_METHOD
Compile: PASS
Tests: PASS
Final status: VERIFIED_MIGRATION
```

Exact formatting may differ; these statuses come from structured artifacts, not
provider prose.

## 4. Show the causal evidence and plan

Use the run directory printed by the CLI, or select the newest one:

```bash
RUN_DIR="$(ls -1dt "$DEMO_STATE"/runs/* | head -n 1)"

python3 -m json.tool "$RUN_DIR/causal-diagnosis.json" | sed -n '1,120p'
python3 -m json.tool "$RUN_DIR/migration-plan.json" | sed -n '1,160p'
```

Highlight four facts:

1. `core-lib` is the requested upgrade.
2. `parser-lib` changed transitively.
3. Old/new JAR evidence shows the removed method.
4. The plan bounds source files and preserves dependency/test constraints.

Do not describe candidate APIs as verified replacements. They become verified
only after the resulting patch passes independent checks.

## 5. Show patch and verification

```bash
sed -n '1,220p' "$RUN_DIR/migration-report.txt"
sed -n '1,160p' "$RUN_DIR/final.patch"
```

The known smoke-test patch imports `ParserOptions` and migrates the call to the
new parser API. BumpShield then independently resolves dependencies, compiles,
runs all three tests, checks test integrity, and checks patch scope.

## 6. Prove repository isolation

```bash
FIXTURE_REPO=benchmark/runtime/transitive-removed-method/application

git -C "$FIXTURE_REPO" diff --exit-code
git -C "$FIXTURE_REPO" diff --cached --exit-code
git -C "$FIXTURE_REPO" rev-parse HEAD
git -C "$FIXTURE_REPO" worktree list
```

Expected result: no tracked or index diff, repository still at its updated
commit, and no stale repair worktree. Maven may leave untracked `target/` build
output; BumpShield never applies the winning source patch to this repository.

## Presenter talk track

1. A direct upgrade broke compilation, but the missing API belongs to a
   transitive artifact.
2. BumpShield reproduces the regression before attempting repair.
3. It compares resolved graphs, attributes the class to a real JAR, and proves
   the API change with `javap`.
4. Deterministic diagnosis and planning bound the model's task.
5. Codex proposes source edits in a disposable worktree.
6. BumpShield—not Codex—captures the Git patch, compiles, tests, verifies
   dependency/test integrity, and exports `final.patch`.
7. The original repository remains unchanged.

## What not to demo live

- Do not run BUMP-FINAL-v1; it is frozen, expensive, and already complete.
- Do not present BUMP-FINAL-v1 as production evidence; all 20 cases are
  synthetic.
- Do not claim BumpShield beat direct repair. Strict VRR was 18/20 for
  BumpShield and 20/20 for both direct strategies.
- Do not hide provider quota failures; they are part of strict VRR.

## Fallback without Codex availability

If provider quota or authentication is unavailable, demonstrate deterministic
analysis and planning instead:

```bash
MAVEN_OPTS="-Dmaven.repo.local=$DEMO_M2" \
  bumpshield diagnose benchmark/cases/transitive-removed-method.json \
  --state-dir "$DEMO_STATE"

MAVEN_OPTS="-Dmaven.repo.local=$DEMO_M2" \
  bumpshield plan benchmark/cases/transitive-removed-method.json \
  --state-dir "$DEMO_STATE"
```

Then use the preserved Phase 7.1 report to show the already verified real repair:
[integration-smoke-report.md](integration-smoke-report.md).
