# Agent Instructions and Boundaries

## Development coding agent

Codex was instructed to implement BumpShield phase by phase, inspect existing
code before editing, run deterministic tests, preserve user changes, and report
actual evidence rather than infer success. The governing product constraints
were:

- Java/Maven dependency migrations only;
- reproduce base PASS and updated FAIL before repair;
- distinguish direct from transitive causal dependencies;
- collect API evidence before constructing a diagnosis and plan;
- let Codex propose edits only in an isolated worktree;
- never let provider prose determine success;
- require the independent verifier to retain the upgrade, compile, run tests,
  preserve tests/skips, and accept patch scope;
- never modify the original repository, commit, push, or publish a patch;
- keep benchmark ground truth out of runtime/provider context.

Before the final study, the human froze the configuration, prompts, strategy
budgets, schedule, cases, scoring, repair engine, and verifier. The controlling
instruction after the first final provider call was: do not tune or modify
BumpShield because of benchmark results; if a critical evaluation defect is
found, stop and create a new version rather than patching and continuing.

The complete product and research constraints are preserved in
[`BumpShield_PROJECT_GOAL.md`](../../BumpShield_PROJECT_GOAL.md),
[`docs/evaluation-protocol.md`](../../docs/evaluation-protocol.md), and the
frozen [`benchmark/final-config-v1.json`](../../benchmark/final-config-v1.json).

## Runtime repair agent

The exact provider instruction is built by
[`build_repair_request`](../../bumpshield/agent/provider.py). Its invariant
instructions tell Codex that it is editing an isolated worktree, prohibit Git
history/state changes, require the smallest correct migration, preserve the
upgraded target and tests, avoid unrelated refactors, and prohibit claiming
success. Dynamic sections contain only runtime-derived diagnosis, plan,
constraints, bounded source, and prior attempt feedback.

Codex executes with workspace-write sandboxing, no approval escalation, ignored
ambient user rules/configuration, disabled skill discovery, an ephemeral
session, and a bounded timeout. The implementation is the authoritative prompt
record; replay bundles do not invoke it.

## Baseline repair agents

Direct One-Shot and Direct Retry use the same runtime repair instruction builder
and verifier but receive a neutral plan from
[`DirectBaselinePlanning`](../../bumpshield/evaluation/strategies.py). That plan
contains the target upgrade, bounded updated-build failure, localized source,
and safety constraints. It deliberately contains no dependency diff, `javap`
evidence, causal diagnosis, API candidate, or benchmark ground truth.

- Direct One-Shot changes the repair budget to one call.
- Direct Retry retains the three-call budget and may receive only its own
  execution feedback.
- BumpShield receives the deterministic evidence and plan before the same
  provider/verifier boundary.

Prompt-template hashes are frozen in
[`benchmark/final-config-v1.json`](../../benchmark/final-config-v1.json).
