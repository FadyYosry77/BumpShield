# Five-Minute Submission Video Script

Target duration: 4:30–4:50. Record at 1080p with terminal text at a readable
size. Use the offline BoneCP replay for the main execution so the video does not
depend on provider quota.

## Exact command runbook

Run every command from the BumpShield repository root. These commands are safe
for the video: they do not call Codex, run Maven, use the network, or rerun the
frozen benchmark.

### A. Prepare before recording

Open a terminal and install the project once:

```bash
cd ~/BumpShield
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,demo]'
```

If `.venv` already exists, use only:

```bash
cd ~/BumpShield
source .venv/bin/activate
```

Confirm the GUI port is free:

```bash
curl --fail --silent http://127.0.0.1:8501/_stcore/health || true
```

If this prints `ok`, stop the older Streamlit terminal with `Ctrl+C` before
recording. Close terminals that contain credentials or private paths.

### B. Open two terminals for recording

Use **Terminal 1** for short evidence commands and **Terminal 2** for the GUI.
In both terminals:

```bash
cd ~/BumpShield
source .venv/bin/activate
```

Increase terminal font size before recording. Do not run `pwd`; keeping the
absolute home-directory path off screen makes the video easier to share.

### C. Terminal 1 — identify the system

Run:

```bash
python -m bumpshield.cli version
python -m bumpshield.cli --help
```

Expected important output:

```text
0.1.0
reproduce  dependencies  failures  evidence  diagnose  plan  repair  benchmark
```

Then show the architecture without opening a large document:

```bash
sed -n '1,48p' README.md
```

Say: “Codex proposes edits, but deterministic evidence and the independent
verifier control acceptance.”

### D. Terminal 1 — show the fair baseline setup

Run the development-suite dry run:

```bash
python -m bumpshield.cli benchmark benchmark/bump-dev.json --dry-run
```

Expected important output:

```text
Cases: 4
Strategies: direct-one-shot, direct-retry, bumpshield
Planned case-strategy trials: 12
Maximum provider calls: 28
No repair execution performed.
```

Point out:

- Direct One-Shot gets one call and no causal evidence.
- Direct Retry and BumpShield both get up to three calls.
- The schedule rotates strategy order.
- This command is only a preview; it makes zero provider calls.

Do not run the actual BUMP-DEV provider evaluation during the video.

### E. Terminal 1 — prove frozen research integrity

Run:

```bash
python -m bumpshield.cli benchmark \
  benchmark/bump-final-v1.json \
  --verify-freeze
```

Expected output:

```text
Suite: BUMP-FINAL-v1
Cases: 20
DIRECT: 10
TRANSITIVE: 10
Configuration: 3c0dfaad58f985d1c9a9db7f17ee28a84af7f8b3bcce45de5dd078877943ff56
Dataset: 8bd13704194037bd3c672233af5d4e1102d78cb084aea736dd7738ded37a4e8a
Result: VALID
```

Say: “This validates the preserved definitions; it does not execute or mutate
the final benchmark.”

### F. Terminal 1 — validate the real-world replay bundle

Copy and run this complete block:

```bash
python - <<'PY'
from demo_ui.replay import REAL_WORLD_REPLAY_BUNDLE, RecordedRunSource

bundle = RecordedRunSource.load(REAL_WORLD_REPLAY_BUNDLE).bundle
print("Bundle:", bundle.bundle_id)
print("Mode: RECORDED REAL-WORLD VERIFIED RUN")
print("Final status:", bundle.verification.final_status)
print("Bundle SHA-256:", bundle.bundle_hash)
print("Original repository unchanged:", bundle.provenance.original_repository_unchanged)
PY
```

Expected output:

```text
Bundle: bonecp-guava-real-world-v1
Mode: RECORDED REAL-WORLD VERIFIED RUN
Final status: VERIFIED_MIGRATION
Bundle SHA-256: 0c1cfd2208d606ce2b81a065cd6a6593134427864d16cf2e39e64b29ddcf9b9b
Original repository unchanged: True
```

### G. Terminal 2 — launch the GUI

Run:

```bash
python -m streamlit run demo_ui/app.py \
  --server.headless true \
  --server.port 8501 \
  --browser.gatherUsageStats false
```

Wait for:

```text
Local URL: http://localhost:8501
```

Open `http://localhost:8501` in the browser. Keep Terminal 2 running until the
recording ends.

In the GUI:

1. Keep **Recorded Verified Run** selected.
2. Select **BoneCP Real-World Showcase**.
3. Confirm the label says **RECORDED REAL-WORLD VERIFIED RUN**.
4. Confirm artifact integrity is valid.
5. Click **Start Replay**.
6. Use **Next** through all ten stages.

No terminal command is needed between GUI stages. The browser is reading the
already validated evidence bundle.

### H. Optional Terminal 1 commands for detailed BoneCP evidence

Use these only if a GUI panel is hard to read. Each prints a small committed
artifact and performs no live execution.

Regression:

```bash
python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/reproduction.json
```

Dependency transition:

```bash
python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/dependency-diff.json
```

Localized failure:

```bash
python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/failure.json
```

API evidence and diagnosis:

```bash
python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/api-evidence.json

python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/diagnosis.json
```

Migration plan:

```bash
python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/migration-plan.json | sed -n '1,180p'
```

Git-ground-truth patch:

```bash
sed -n '1,180p' \
  demo_ui/replay/bonecp-real-world-v1/patch.diff
```

Compile/test record and independent verification:

```bash
python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/execution.json

python -m json.tool \
  demo_ui/replay/bonecp-real-world-v1/verification.json
```

### I. Terminal 1 — print the final comparison cleanly

Copy and run this block:

```bash
python - <<'PY'
import json
from pathlib import Path

summary = json.loads(
    Path("benchmark/results/BUMP-FINAL-v1/summary.json").read_text()
)
rows = {row["strategy"]: row for row in summary["overall"]}
order = ("direct-one-shot", "direct-retry", "bumpshield")

print("BUMP-FINAL-v1 — frozen 20-case synthetic evaluation")
print(f"{'Strategy':20} {'Verified':10} {'Strict VRR':12} {'Provider calls'}")
for name in order:
    row = rows[name]
    verified = f"{row['verified']}/{row['attempted_valid']}"
    strict = f"{100 * row['strict_vrr']:.0f}%"
    print(f"{name:20} {verified:10} {strict:12} {row['provider_calls']}")

root = summary["root_cause"]
print()
print("BumpShield dependency root cause:",
      f"{root['dependency_correct']}/{root['dependency_labeled']}")
print("BumpShield exact API change:",
      f"{root['api_correct']}/{root['api_labeled']}")
print("BumpShield provider-available VRR: 18/18")
print("Provider quota failures: 2")
PY
```

Expected table:

```text
BUMP-FINAL-v1 — frozen 20-case synthetic evaluation
Strategy             Verified   Strict VRR   Provider calls
direct-one-shot      20/20      100%         20
direct-retry         20/20      100%         20
bumpshield           18/20      90%          24

BumpShield dependency root cause: 20/20
BumpShield exact API change: 12/20
BumpShield provider-available VRR: 18/18
Provider quota failures: 2
```

Say explicitly: “The baseline won strict repair rate. I did not tune BumpShield
or rerun failed cases after seeing this result.”

### J. Terminal 1 — show tests and changelog

Run the full deterministic suite if recording time permits:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  python -m pytest -p no:cacheprovider -q
```

Expected final line:

```text
276 passed
```

Then show the changelog headings:

```bash
rg '^## ' docs/improvement-changelog.md
```

To show the removed live-only experiment:

```bash
sed -n '/## Iteration 6/,/## Iteration 7/p' \
  docs/improvement-changelog.md
```

### K. Stop after recording

Return to Terminal 2 and press:

```text
Ctrl+C
```

Do not leave the Streamlit server running unnecessarily.

## Commands never to run in the submission video

Do **not** run any of these during recording:

```bash
# Do not rerun the frozen provider-backed evaluation.
python -m bumpshield.cli benchmark benchmark/bump-final-v1.json

# Do not start a provider-backed repair unless you deliberately want a live,
# quota-dependent demonstration.
python -m bumpshield.cli repair task.json

# Do not expose environment variables, credentials, or absolute home paths.
env
printenv
pwd
```

Use `--verify-freeze`, `--dry-run`, replay validation, and committed results
instead.

## 0:00–0:35 — Problem and user

Show the README title and one dependency chain.

Talk track: “BumpShield is for Java maintainers whose Maven project breaks after
a dependency upgrade. The compiler shows where source failed, but a direct
upgrade can silently change a transitive JAR. Maintainers still have to find
the causal dependency, prove the API change, bound the migration, and determine
whether an AI patch is actually safe.”

## 0:35–1:00 — Baseline versus advanced workflow

Show the comparison table in `SUBMISSION.md`.

Talk track: “The baseline gets the upgrade, failure, and source. Direct
One-Shot gets one attempt; Direct Retry gets the same three-attempt budget as
BumpShield. BumpShield adds deterministic dependency diff, JAR/API evidence,
causal diagnosis, and a migration plan. Every strategy is judged by the same
independent verifier.”

## 1:00–3:15 — Realistic end-to-end execution

Launch before recording:

```bash
streamlit run demo_ui/app.py
```

Select **Recorded Verified Run**, then **BoneCP Real-World Showcase**, and click
**Start Replay**.

Show these stages in order:

1. BoneCP base build: 197 tests pass.
2. Constructed Guava 15-to-21 upgrade: updated build fails.
3. Two production uses of `Objects.toStringHelper(...)` are localized.
4. Old/new JAR evidence proves the member is present in Guava 15 and absent in
   Guava 21.
5. Diagnosis is `SUPPORTED_DIAGNOSIS`, 100/100 ordinal evidence; plan bounds
   repair to two files.
6. Recorded Git patch changes `Objects` to `MoreObjects`, +4/-4.
7. Independent verification retains Guava 21, compiles, runs 197 tests, checks
   test integrity, test skips, dependency constraints, and patch scope.
8. End on `VERIFIED_MIGRATION` and the integrity badge.

Say clearly: “This is an integrity-checked replay of a real provider-backed run,
not a simulated repair. Replay invokes no provider or build tools. BoneCP is a
constructed upgrade on genuine open-source source and is separate from the
frozen benchmark.”

## 3:15–4:05 — Final comparison

Show the BUMP-FINAL table in `SUBMISSION.md` or the GUI Evidence & Results page.

Talk track: “On 20 unseen synthetic cases, Direct One-Shot and Direct Retry both
verified 20 of 20. BumpShield verified 18 of 20 strict; both failures were
provider quota, and it verified 18 of 18 available trials. The benchmark did
not show a repair-rate advantage. It did show 20-of-20 causal dependency
accuracy, including every transitive case, while preserving auditable evidence
and verification.”

## 4:05–4:35 — Changelog and removed experiment

Show `docs/improvement-changelog.md`.

Talk track: “The biggest contribution is separating AI proposal from causal
evidence and independent acceptance. One experiment we removed was the
live-only judge demo. Quota failures made it fragile, so recorded verified
replay became the default while live mode stayed optional. We also added the
matched retry baseline and kept its winning result rather than tuning after the
freeze.”

## 4:35–4:50 — Failure mode and hot take

Talk track: “The main failure mode is provider availability. My hot take is
that an agent should never grade its own patch: an honest verified result—even
when the baseline wins—is more useful than a confident success message.”

## Recording checklist

- Keep the final video at or below five minutes.
- Show the project name and intended user in the first 30 seconds.
- Keep `RECORDED REAL-WORLD VERIFIED RUN` visible.
- Do not claim BoneCP is a historical upstream regression.
- Do not claim BumpShield beat direct repair.
- Do not show credentials, home-directory paths, browser account data, or raw
  provider logs.
- Add captions if the upload platform supports them.
- Paste the final public/unlisted video URL into the submission form and the
  checklist; do not commit a private upload token.
