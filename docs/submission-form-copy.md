# Copy-Ready Submission Form Text

Replace the two URL placeholders after publishing. Keep the quantitative claims
unchanged unless a new, separately versioned evaluation is run.

## Project name

BumpShield

## One-line description

A causal Java/Maven dependency-migration agent that explains why an upgrade
broke, constrains an AI repair, and independently proves the patch by execution.

## Problem and user

BumpShield serves Java maintainers and platform engineers handling failed Maven
dependency upgrades. A direct upgrade can change a transitive JAR, so a compiler
error reveals the broken call but not the causal dependency path, old/new API
change, safe edit boundary, or behavioral validity. BumpShield reconstructs
those facts before repair and preserves them as auditable artifacts.

## Baseline and advanced solution

Direct One-Shot receives the target upgrade, bounded build failure, and source
context for one repair attempt. Direct Retry receives the same limited context
for up to three attempts. BumpShield receives up to three attempts after
deterministic dependency diff, JAR/API evidence, causal diagnosis, and bounded
migration planning. All strategies use the same independent verifier.

## Main result

On frozen BUMP-FINAL-v1 (20 unseen synthetic cases, 60 counterbalanced trials),
Direct One-Shot and Direct Retry each verified 20/20; BumpShield verified 18/20
strict and 18/18 provider-available. Its two strict failures were provider quota
failures. BumpShield localized the causal dependency in 20/20 cases, including
10/10 transitive cases; exact API-change accuracy was 12/20. This benchmark did
not show a repair-rate advantage for causal analysis.

A separate real-world BoneCP showcase used genuine Apache-2.0 project source
with a clearly labeled constructed Guava 15-to-21 upgrade. BumpShield produced
a two-file +4/-4 migration and independently passed compilation and 197 tests.
This showcase is not counted in BUMP-FINAL rates.

## Biggest engineering contribution

The coding model cannot grade its own patch. Codex edits only a disposable Git
worktree; Git captures the actual patch, and BumpShield independently verifies
dependency retention, compilation, tests, test inventory and skips, scope, and
safety before emitting `VERIFIED_MIGRATION`.

## Removed experiment and failure mode

The live-only judge demo was removed as the default after quota failures showed
it was operationally fragile. An integrity-checked replay of a real verified run
is now the default; live mode remains optional. Provider availability remains
the main failure mode and is reported separately without rewriting strict
results.

## Hot take

An agent should never grade its own patch. A fair baseline that wins and a
verifier-controlled failure are more valuable than a confident success message.

## Links

- Repository: `https://github.com/FadyYosry77/BumpShield`
- Video: `https://drive.google.com/file/d/16wg-Q1MrWquszqIpJq8O4qjMoAHLgVvm/view?usp=sharing`
- Submission overview: `SUBMISSION.md`
- Reproduction: `docs/reproduction-guide.md`
- Agent trajectories: `submission/agent-trajectories/README.md`
