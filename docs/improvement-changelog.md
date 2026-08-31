# Improvement Changelog

This changelog records meaningful system iterations, why each was made, the
evidence used to judge it, and the resulting decision. Frozen
`BUMP-FINAL-v1` behavior was never tuned after its results were observed.

## Baseline: direct repair

The initial comparison was a Direct One-Shot coding-agent repair. It receives
the upgraded dependency, bounded build failure, and source context, then gets
one attempt. This remained the primary minimal baseline. A Direct Retry baseline
was later added with the same limited context and the same three-attempt budget
as BumpShield, isolating the effect of causal evidence from retry feedback.

Decision: keep both baselines and run every strategy through the same verifier.

## Iteration 1: deterministic regression and dependency evidence

Why: a compiler error alone does not prove that the declared upgrade caused
the failure, especially when a direct dependency changes a transitive artifact.

Change: add isolated base/updated reproduction, resolved Maven graph comparison,
failure parsing, safe source localization, JAR ownership, and `javap` API
comparison.

Evidence: the integration fixture recovered the direct-to-transitive path and
the removed API. In the final evaluation, dependency root-cause localization
was 20/20, including 10/10 transitive cases.

Decision: keep. Exact API-change accuracy was only 12/20, so candidates remain
explicitly labeled as evidence rather than guaranteed semantic replacements.

## Iteration 2: explicit diagnosis and bounded planning

Why: giving a coding model raw logs leaves the causal theory and edit boundary
implicit.

Change: build an ordinal, deterministic causal diagnosis and a migration plan
that lists allowed files, protected files, dependency constraints, candidate
APIs, and verification requirements.

Evidence: all 20 final cases produced a supported diagnosis and ready plan.

Decision: keep the structured artifacts. Do not describe the score as a
probability and do not claim that a planned candidate is already correct.

## Iteration 3: isolated repair and independent verification

Why: provider prose and a plausible diff do not prove a migration. Repairs also
must not damage the original repository or weaken tests.

Change: let Codex edit a disposable Git worktree, derive the patch from Git,
and require compile, tests, dependency guards, test-integrity, test-skip, scope,
and safety checks before emitting `VERIFIED_MIGRATION`.

Evidence: the controlled end-to-end smoke case and the BoneCP showcase both
reached verified migration while their original repositories remained
unchanged. BoneCP passed 197 tests with the upgraded dependency retained.

Decision: keep. The model proposes; BumpShield verifies.

## Iteration 4: matched evaluation and frozen methodology

Why: comparing one direct attempt with three BumpShield attempts would confound
causal analysis with retry budget.

Change: add Direct Retry, counterbalance execution order, freeze prompts,
budgets, scoring, verifier policy, configuration hash, dataset hash, and rerun
policy before provider-backed final execution.

Evidence: Direct One-Shot and Direct Retry both achieved 20/20 strict VRR;
BumpShield achieved 18/20 strict and 18/18 provider-available. The matched
comparison did not show a repair-rate benefit from causal analysis.

Decision: preserve the unfavorable result. No prompt, planner, repair, or
verifier tuning was performed in response.

## Iteration 5: resumable execution and operational accounting

Why: provider quota, authentication, or service outages should pause a run,
not manufacture failures for unexecuted trials or erase attempted failures.

Change: persist each trial immediately, classify provider failures, pause on
global unavailability, and resume without rewriting completed rows.

Evidence: two final quota failures remained visible in strict VRR; all 18
provider-available BumpShield trials verified.

Decision: keep strict VRR as primary and provider-available VRR as a labeled
secondary operational metric.

## Iteration 6: GUI presentation and offline replay

Why: a live-only judge demo depended on network, Maven, Java, Codex
authentication, and quota at presentation time.

Change: retain an explicit live mode, but make Recorded Verified Run the
default. Replay validates every artifact hash and invokes no provider, network,
Maven, Java, Git worktree, or repair code.

Evidence: both committed replay bundles load with matching SHA-256 integrity
and end at recorded `VERIFIED_MIGRATION`.

Decision: remove the live-only default. Never relabel replay as a new run.

## Iteration 7: real-world BoneCP showcase

Why: all 20 final benchmark cases are synthetic, limiting external validity.

Change: construct a separately labeled Guava 15-to-21 upgrade on genuine BoneCP
source, run the unchanged BumpShield v1 pipeline, preserve sanitized evidence,
and add it to replay.

Evidence: one fresh attempt produced a two-file +4/-4 patch; compilation and
197 tests passed; all verifier guards passed. An earlier quota-interrupted patch
was not accepted manually.

Decision: keep as a one-project showcase, not as a post-hoc benchmark extension.

## What existed before the challenge

No BumpShield implementation, benchmark, GUI, replay bundle, or result artifact
predated the challenge in this workspace. The repository history is not
available in this exported workspace, so this statement is based on the
challenge work record rather than a reconstructable public commit history.
