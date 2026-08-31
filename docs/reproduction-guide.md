# Clean-Environment Reproduction Guide

This guide separates three tasks: verifying the submission without a provider,
running the product on a migration, and running a new development evaluation.
The completed `BUMP-FINAL-v1` evaluation is frozen and must not be rerun under
modified behavior.

## Tested environment

The final evaluation used:

- Linux x86-64 with glibc 2.39
- Python 3.12.3 (supported minimum: 3.11)
- Git 2.43.0
- Eclipse Temurin/OpenJDK 21.0.12.1 with `javap`
- Maven 3.9.16
- Codex CLI 0.151.0 for provider-backed repair

Offline replay and deterministic tests do not require Java, Maven, Codex,
provider credentials, or network access.

## 1. Install from a clean checkout

```bash
git clone https://github.com/FadyYosry77/BumpShield.git
cd BumpShield
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,demo]'
```

If using the submitted ZIP instead of Git, extract it, enter its top-level
directory, and start at the `python3 -m venv` command.

The video-inclusive ZIP also contains
`submission/video/BumpShield-demo.mp4`. The video is not required to run or test
the project.

## 2. Deterministic qualification path

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -p no:cacheprovider

python -m bumpshield.cli benchmark \
  benchmark/bump-final-v1.json \
  --verify-freeze

python - <<'PY'
from demo_ui.replay import DEFAULT_REPLAY_BUNDLE, REAL_WORLD_REPLAY_BUNDLE
from demo_ui.replay import RecordedRunSource

for path in (DEFAULT_REPLAY_BUNDLE, REAL_WORLD_REPLAY_BUNDLE):
    bundle = RecordedRunSource.load(path).bundle
    print(bundle.bundle_id, bundle.verification.final_status, bundle.bundle_hash)
PY
```

Expected results:

- all deterministic tests pass;
- configuration hash is
  `3c0dfaad58f985d1c9a9db7f17ee28a84af7f8b3bcce45de5dd078877943ff56`;
- dataset hash is
  `8bd13704194037bd3c672233af5d4e1102d78cb084aea736dd7738ded37a4e8a`;
- both replay bundles report `VERIFIED_MIGRATION`.

Typical runtime on the tested laptop is under 15 seconds after dependencies
are installed. Provider calls: zero. Monetary provider cost: zero.

## 3. Run the offline GUI

```bash
streamlit run demo_ui/app.py
```

Open `http://localhost:8501`, keep **Recorded Verified Run** selected, and
choose either the synthetic transitive run or the BoneCP real-world showcase.
Replay validates committed hashes and performs no external execution.

For a headless smoke check:

```bash
python -m pytest -p no:cacheprovider tests/test_demo_ui_adapters.py \
  tests/test_demo_ui_replay.py
```

## 4. Run the baseline and advanced systems on BUMP-DEV

This is a new development evaluation, not a rerun of the frozen final study.
It requires Git, Java, Maven, network access for initial Maven resolution, and
an authenticated Codex CLI.

Preview the exact fair schedule without provider or build execution:

```bash
bumpshield benchmark benchmark/bump-dev.json --dry-run
```

Expected preview: 4 cases, 3 strategies, 12 case-strategy trials, and at most
28 provider calls. The named strategies include the Direct One-Shot baseline,
Direct Retry matched baseline, and advanced BumpShield workflow.

Prepare public/synthetic fixture dependencies into a disposable cache:

```bash
python benchmark/prepare_bump_dev.py \
  --maven mvn \
  --maven-repository /tmp/bump-dev-m2
```

Run all strategies through the same verifier:

```bash
MAVEN_OPTS=-Dmaven.repo.local=/tmp/bump-dev-m2 \
  bumpshield benchmark benchmark/bump-dev.json \
  --state-dir /tmp/bumpshield-dev-state
```

Outputs are written under
`/tmp/bumpshield-dev-state/benchmarks/<benchmark-run-id>/`, including
`results.csv`, `results.json`, `summary.json`, `summary.md`, and the persisted
schedule. Runtime depends on provider and Maven latency; budget roughly 20–45
minutes. Maximum provider calls: 28. Dollar cost is not estimated because the
Codex CLI did not expose per-call billing in the captured evidence; use the
operator's plan/quota dashboard.

## 5. Run BumpShield on a Java/Maven migration

Create `task.json` with a passing commit, a failing dependency-upgrade commit,
and the target Maven coordinate:

```json
{
  "repository": "/absolute/path/to/project",
  "base_commit": "<passing-sha>",
  "updated_commit": "<failing-upgrade-sha>",
  "target_dependency": {
    "group_id": "org.example",
    "artifact_id": "library",
    "old_version": "1.0.0",
    "new_version": "2.0.0"
  }
}
```

Run deterministic investigation first:

```bash
bumpshield reproduce task.json --state-dir /tmp/bumpshield-state
bumpshield dependencies task.json --state-dir /tmp/bumpshield-state
bumpshield failures task.json --state-dir /tmp/bumpshield-state
bumpshield evidence task.json --state-dir /tmp/bumpshield-state
bumpshield diagnose task.json --state-dir /tmp/bumpshield-state
bumpshield plan task.json --state-dir /tmp/bumpshield-state
```

Then explicitly authorize provider-backed repair:

```bash
bumpshield repair task.json --state-dir /tmp/bumpshield-state
```

The command prints the run directory. A successful run contains
`final.patch`, `migration-report.txt`, diagnosis, plan, attempts, and verifier
artifacts. The original repository is not patched, committed, or pushed.

## 6. Reproduce the published final metrics without rerunning repairs

The lightweight result snapshot is committed under
`benchmark/results/BUMP-FINAL-v1/`. Inspect it directly:

```bash
python -m json.tool \
  benchmark/results/BUMP-FINAL-v1/summary.json | less

sed -n '1,220p' \
  benchmark/results/BUMP-FINAL-v1/summary.md
```

The original final run used 60 trials and 64 actual provider calls. Active
repair time was approximately 90 minutes before operational pauses. No dollar
cost was recorded by the provider CLI. Do not execute another provider-backed
run under the `BUMP-FINAL-v1` name.

## Data and safety

- BUMP-DEV and BUMP-FINAL use repository-owned synthetic Java/Maven fixtures.
- BoneCP is a separately labeled, Apache-2.0 public-source showcase; no upstream
  clone or cache is bundled.
- Provider credentials are read by the operator's Codex CLI and never stored in
  BumpShield artifacts.
- Repair is sandboxed in disposable Git worktrees. Applying a successful patch,
  committing it, pushing it, or opening a pull request always requires a human.

For full command behavior and troubleshooting, see the
[usage guide](usage-guide.md).
