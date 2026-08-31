# Representative Agent Trajectories

These trajectories provide a concise, reviewable chain from instructions to
result. They identify tool feedback, retries, and human checkpoints without
including credentials, private account data, or large transient logs.
The exact governing instructions and source prompt locations are indexed in
[Agent Instructions and Boundaries](../agent-instructions/README.md).

## Agent inventory

| Agent/workflow | Role | Input | Authority boundary |
|---|---|---|---|
| Codex coding agent | Built and tested BumpShield | Phase specifications, repository, command feedback | Could edit this workspace; human set scope and freeze rules |
| Direct One-Shot repair provider | Minimal evaluation baseline | Upgrade, bounded failure, source | Patch proposal only; independent verifier accepts/rejects |
| Direct Retry repair provider | Matched retry baseline | Same limited context plus prior execution feedback | Up to three proposals; same verifier |
| BumpShield repair provider | Advanced repair step | Deterministically derived evidence, plan, bounded source | Patch proposal only in disposable worktree |

Reproduction, dependency analysis, failure localization, API evidence,
diagnosis, planning, Git patch extraction, and verification are deterministic
components. They are not separate language-model agents.

## Trajectory 1 — building the system

**Instruction.** Build a Java/Maven dependency-migration agent that explains
direct and transitive breakage, uses Codex only for bounded repair, and never
accepts a patch without independent execution.

**Actions and tool responses.**

1. Inspected the existing workspace and phase requirements.
2. Implemented each deterministic stage and exercised it with focused tests.
3. Ran Git/Maven/Java integration fixtures. Tool feedback exposed real compiler
   failures and dependency paths, which became regression tests.
4. Added Codex repair in isolated worktrees. Git diff, compile, tests, and guard
   outcomes—not provider prose—became the result source.
5. Ran the deterministic suite after each phase and stopped on failures.

**Feedback and retry loop.** Failing tests and command output drove narrow
implementation fixes before the evaluation freeze. Provider repair failures did
not authorize manually changing a patch or verifier.

**Human checkpoints.** The human approved the research question, strategy
budgets, final configuration, and absolute post-freeze rule. Once provider-
backed final evaluation began, the coding agent was forbidden from changing
causal analysis, prompts, planning, repair, verification, cases, or scoring in
response to outcomes.

**Result.** A deterministic pipeline plus bounded repair and independent
verification, a frozen 60-trial evaluation, offline replay, and a separately
labeled BoneCP showcase.

## Trajectory 2 — runtime BumpShield repair agent

**Instruction supplied to the provider.** Repair only the planned Java source
files for the already-upgraded project. Preserve the target dependency, tests,
and behavior. Do not edit protected build/test files or claim verification.

**Deterministic context supplied.** BumpShield supplied the reproduced failure,
resolved dependency transition, JAR ownership and old/new public API evidence,
causal diagnosis, allowed-file plan, bounded source, and repair constraints.
Benchmark ground truth was not supplied.

**Provider action.** Codex edited a disposable worktree and returned control.

**Tool responses.** BumpShield read the actual Git diff, then independently
resolved dependencies, compiled, ran tests, compared test inventory and skips,
checked dependency preservation, and checked patch scope. Only a fully passing
chain produced `VERIFIED_MIGRATION`.

**Retries.** Up to three attempts were permitted by the frozen configuration.
Execution feedback could inform a later attempt; attempt history remained in
artifacts. Global quota/authentication/service unavailability paused remaining
work instead of inventing unexecuted failures.

**Human checkpoint.** No provider patch was applied to the original repository,
committed, pushed, or published. Those consequential actions remained outside
agent authority.

**Result.** In BUMP-FINAL-v1, 18/20 strict trials and 18/18 provider-available
trials verified. Two quota failures stayed failures. Dependency root-cause
localization was 20/20.

## Trajectory 3 — Direct baselines

**Instruction supplied to the provider.** Repair the dependency-upgrade build
failure using only the target upgrade, bounded build output, and source context.

**Baseline difference.** Direct One-Shot allowed one attempt. Direct Retry
allowed up to three and could receive its own execution feedback. Neither
received BumpShield's dependency path, API diff, diagnosis, migration plan, or
benchmark ground truth.

**Tool response and acceptance.** Both strategies used the exact same
independent verifier and Git-ground-truth patch analysis as BumpShield.

**Result.** Both baselines verified 20/20 final cases, usually on their first
attempt. This result was preserved even though it did not support a repair-rate
advantage for the advanced workflow.

## Trajectory 4 — BoneCP real-world showcase

**Instruction.** Apply unchanged BumpShield v1 to a genuine open-source Maven
project without altering frozen BUMP-FINAL behavior. Use a clearly labeled
constructed Guava 15-to-21 upgrade and independently verify any patch.

**First provider response.** Codex produced a plausible patch, then quota
expired before the full accepted result. The patch was not manually promoted to
success.

**Human checkpoint.** The human authorized one fresh showcase attempt. This was
not a BUMP-FINAL rerun and could not change BumpShield v1.

**Second provider response.** Codex replaced two `Objects.toStringHelper` uses
with `MoreObjects.toStringHelper` inside the two-file plan boundary.

**Independent tool responses.** Git recorded +4/-4 across two files; Guava 21
remained resolved; compilation passed; 197 tests passed with the same three
pre-existing skips; dependency, integrity, skip, scope, and safety checks
passed.

**Result.** `VERIFIED_MIGRATION`. Sanitized evidence and SHA-256 hashes were
packaged into offline replay. The case remains a one-project showcase, not a
benchmark statistic.

## Evidence links

- [Frozen result snapshot](../../benchmark/results/BUMP-FINAL-v1/summary.md)
- [Evaluation protocol](../../docs/evaluation-protocol.md)
- [BoneCP evidence](../../docs/real-world-showcase.md)
- [Replay implementation](../../demo_ui/replay.py)
- [Improvement changelog](../../docs/improvement-changelog.md)
