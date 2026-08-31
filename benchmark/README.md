# BumpShield benchmarks

This directory contains BumpShield's development and frozen final evaluation
assets. Benchmark execution is explicit: normal unit tests never invoke Java,
Maven, Codex, or the network.

Every repair strategy is judged by the same independent verifier. Only
`VERIFIED_MIGRATION` counts as success. Strict Verified Repair Rate (VRR) keeps
attempted provider failures in its denominator; provider-available VRR is a
secondary operational metric.

## Strategies

- **Direct One-Shot** receives the target upgrade, bounded build failure, and
  source context. It gets one provider call and no BumpShield causal evidence.
- **Direct Retry** receives the same limited context and up to three calls with
  execution feedback.
- **BumpShield** receives up to three calls after deterministic dependency,
  failure, API, diagnosis, and migration-planning stages.

Ground truth is used only after execution to score localization. It is never
passed to a repair provider or BumpShield's runtime pipeline.

## BUMP-DEV

BUMP-DEV is a four-case synthetic development suite: direct removed method,
transitive removed method, direct signature change, and transitive removed
class. It exercises the harness and is not an unseen research benchmark.

Preview its counterbalanced schedule and maximum provider calls without Git,
Maven, Java, or Codex execution:

```bash
bumpshield benchmark benchmark/bump-dev.json --dry-run
```

Prepare its fixture repositories and a disposable Maven cache:

```bash
python3 benchmark/prepare_bump_dev.py \
  --maven mvn \
  --maven-repository /tmp/bump-dev-m2
```

Then run it with the same cache:

```bash
MAVEN_OPTS=-Dmaven.repo.local=/tmp/bump-dev-m2 \
  bumpshield benchmark benchmark/bump-dev.json \
  --state-dir /tmp/bumpshield-state
```

Generated repositories live under ignored `benchmark/runtime/`. Evaluation
state lives under `<state-dir>/benchmarks/<benchmark-run-id>/`; detailed repair
runs remain under `<state-dir>/runs/` and are referenced rather than copied.

## BUMP-FINAL-v1

BUMP-FINAL-v1 is the completed frozen evaluation. It contains 20 controlled
synthetic cases: 10 direct and 10 transitive, spanning removed methods, changed
signatures, removed classes, removed packages, and removed dependencies.

- Frozen configuration: [`final-config-v1.json`](final-config-v1.json)
- Dataset manifest: [`bump-final-v1.json`](bump-final-v1.json)
- Dataset lock: [`bump-final-v1.lock.json`](bump-final-v1.lock.json)
- Lightweight result snapshot: [`results/BUMP-FINAL-v1/`](results/BUMP-FINAL-v1/)
- Full interpretation: [`../docs/final-research-results.md`](../docs/final-research-results.md)

Frozen hashes:

```text
configuration  3c0dfaad58f985d1c9a9db7f17ee28a84af7f8b3bcce45de5dd078877943ff56
dataset        8bd13704194037bd3c672233af5d4e1102d78cb084aea736dd7738ded37a4e8a
```

Strict results were Direct One-Shot 20/20, Direct Retry 20/20, and BumpShield
18/20. BumpShield's two failures were provider quota failures; its
provider-available result was 18/18. The frozen benchmark did not demonstrate a
repair-rate advantage for causal analysis. It did show 20/20 causal dependency
localization, including 10/10 transitive cases. All cases are synthetic, so the
result does not establish production-project generality.

The final configuration, dataset, prompts, strategy budgets, scheduling policy,
and verifier are immutable research evidence. Future experiments require a new
version; do not rerun modified behavior under the BUMP-FINAL-v1 name.

## Validate and freeze

Fixture preparation requires a JDK and Maven but makes zero provider calls.
The final preparation script builds the tiny libraries, creates ignored fixture
repositories under `benchmark/final-runtime/`, and proves base PASS plus updated
FAIL for every case.

```bash
python3 benchmark/prepare_bump_final.py \
  --maven mvn \
  --maven-repository /tmp/bump-final-m2

MAVEN_OPTS=-Dmaven.repo.local=/tmp/bump-final-m2 \
  bumpshield benchmark benchmark/bump-final-v1.json --validate-only

bumpshield benchmark benchmark/bump-final-v1.json --verify-freeze
```

These commands validate frozen evidence; they do not authorize another
provider-backed BUMP-FINAL-v1 evaluation.

## Resume behavior

Each case/strategy/trial result is persisted immediately. Resume an interrupted
development or new-version benchmark with:

```bash
bumpshield benchmark <suite.json> \
  --state-dir <state-dir> \
  --resume <benchmark-run-id>
```

Completed rows are skipped. `--rerun` replaces rows and therefore must not be
used to improve frozen final results. A global provider quota, authentication,
or service failure pauses later work; resume continues unexecuted rows after
recovery without rewriting the attempted failure.

## Add a case

1. Add a JSON manifest under `benchmark/cases/`.
2. Embed a normal `TaskSpec`, case type, source, split, tags, and defensible
   optional ground truth.
3. Keep ground truth out of runtime source and provider context.
4. Reference the case from a versioned suite manifest.
5. Prove base tests pass, updated tests fail, and target old/new versions resolve.
6. Use a new suite/config version for post-freeze research.

## Outputs

- `results.csv`: one row per case, strategy, and trial.
- `results.json`: complete typed result rows.
- `summary.json`: deterministic aggregate metrics.
- `summary.md`: neutral descriptive report.
- `execution-schedule.json`: persisted counterbalanced order.
- `cases/.../validation.json`: case-validity evidence references.

`INVALID_CASE` is excluded from the strict VRR denominator because no valid
repair trial occurred. Attempted provider failures remain in strict VRR.
