# BumpShield evaluation protocol

## Research question

Does explicit causal dependency analysis improve independently verified repair
of breaking Java/Maven dependency upgrades compared with direct LLM repair?

The main hypothesis is that the largest improvement should occur on transitive
breakages, where the intentionally upgraded artifact is not the artifact that
contains the broken API. Results may reject this hypothesis.

## Strategies

`bumpshield` runs the frozen Phase 0–7.1 pipeline: reproduction, dependency
comparison, failure localization, JAR/API evidence, deterministic diagnosis,
bounded planning, Codex repair, Maven execution, and independent verification.
It permits at most three provider attempts.

`direct-one-shot` receives the target upgrade, bounded updated-build failure,
localized source context, and the same anti-cheating constraints. It receives no
dependency diff, changed transitive list, JAR ownership, `javap` output, causal
diagnosis, migration recommendation, or benchmark ground truth. It gets exactly
one provider invocation.

`direct-retry` receives exactly the same initial evidence as direct one-shot and
up to three provider invocations. Later attempts receive only bounded compile,
test, patch, and safety feedback produced by their own prior attempts. They never
receive dependency analysis, API evidence, BumpShield diagnosis, migration
planning, or benchmark ground truth.

All three strategies use the same Codex configuration, isolated
updated-revision worktrees, Git patch capture, dependency guard, compile/test
execution, test-integrity checks, scope checks, and `IndependentVerifier`.

## Scheduling fairness

Strategy execution uses deterministic counterbalanced rotation. With three
strategies, each consecutive case rotates which strategy runs first, middle, and
last. Trial index also contributes to rotation. The complete planned schedule
and each result's actual execution position are persisted. No randomness or
unrecorded seed is used.

## Valid cases

A case is valid only when repository/commits exist, base tests pass, updated
tests fail, and Maven resolves the declared target old/new versions. Invalid
cases are explicit and excluded from repair-rate denominators.

## Metrics

Verified Repair Rate (VRR) is:

```text
VERIFIED_MIGRATION trials / valid attempted case-strategy trials
```

Provider claims never count. Verification requires upgraded dependency
resolution, compile and tests, test integrity, and acceptable patch safety.

Strict VRR is the primary metric. Every valid attempted trial remains in its
denominator, including provider and infrastructure failures. This denominator
is never rewritten after results are observed.

Provider-available VRR is secondary:

```text
verified migrations / trials where provider and execution infrastructure ran
```

Reports show both denominators, provider failure rate, infrastructure failure
rate, repair failure rate, provider calls per verified repair, and metrics over
verified repairs separately from all trials. This prevents fast quota failures
from making repair runtime or patch size appear artificially small.

Secondary metrics include diagnosis status/strength/score, root-cause dependency
and API-change accuracy, provider calls, attempts, total/provider/compile/test
durations, changed files/lines, patch size (added plus removed lines), rejection
rates, outcome rates, and categorical failures. Missing token/cost data remains
unavailable; it is never invented.

Metrics are reported overall, by direct/transitive case type, and by failure
kind. Initial reports are descriptive. Small suites do not establish statistical
significance.

## Failure policy and circuit breaker

Failures are classified as repair, verification, provider, infrastructure, or
case validation. Provider failures are conservatively refined into unavailable,
timeout, quota, authentication, service-unavailable, non-zero-exit, or unknown
categories. Raw provider output remains in attempt artifacts.

Quota, authentication, executable-unavailable, or service-unavailable evidence
pauses the benchmark after persisting the attempted trial. Later trials remain
unexecuted rather than becoming manufactured failures. Resume skips completed
rows, preserves the failed trial unless `--rerun` is explicit, and continues the
unexecuted schedule after recovery.

## Ground-truth isolation

Ground truth is evaluation-only. The runner does not add it to `TaskSpec`,
`EvidenceBundle`, `RepairContext`, direct prompts, or BumpShield services.
BumpShield must discover causal dependencies normally. Labels are compared only
after a strategy returns.

## Reproducibility

Each run persists suite/configuration, strategy order, environment/provider
versions, case validation, immediate trial results, canonical JSON,
deterministic CSV, and generated Markdown. Resume skips complete rows; `--rerun`
replaces them. Fresh worktrees prevent strategy cross-contamination.

Run metadata records the normalized configuration digest, prompt-template
hashes, diagnosis weight hash, verifier policy, attempt budget, execution
position, and provider metadata. Resume rejects model, prompt, strategy, attempt,
or verification-policy drift through the configuration digest. Provider CLI
version drift is recorded and warned because it may affect interpretation.

## Dataset policy

- `DEV`: cases used to build and debug the harness.
- `ARCHITECTURE`: cases used to validate fixed system behavior.
- `FINAL`: frozen unseen cases, not used for prompt tuning or implementation
  fixes where avoidable.

Future target: 5–10 development cases, about 10 architecture cases, and about
20 frozen final cases. Freeze BumpShield, configuration, provider/model,
toolchain, and trial count before final evaluation.

The first frozen configuration is `benchmark/final-config-v1.json`, marked
`FROZEN FOR FINAL EVALUATION`. Any required post-freeze correction creates a new
versioned file; it never silently edits v1 after unseen results.

## Limitations

BUMP-DEV is synthetic and small. Model outputs vary, timings are
machine-dependent, tools affect executability, and existing project tests are
the MVP behavioral oracle. These constraints prohibit broad claims from
development results.
