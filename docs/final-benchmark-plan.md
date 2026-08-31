# Final benchmark plan

**FROZEN FOR FINAL EVALUATION**

Evaluation version: **BumpShield MVP Evaluation v1**  
Frozen configuration: `benchmark/final-config-v1.json`

## Research question

Does explicit causal dependency analysis improve independently verified repair
of breaking Java/Maven dependency upgrades?

The primary hypothesis is that causal dependency and API evidence provides the
largest benefit for transitive failures, where the requested upgrade is not the
artifact containing the broken API.

## Comparisons and hypotheses

Comparison A, direct one-shot versus BumpShield, tests the original end-to-end
research question. Comparison B, direct retry versus BumpShield, matches the
three-attempt budget and better isolates causal evidence from retry feedback.
Comparison C, direct one-shot versus direct retry, measures the value of
iterative execution feedback itself.

- H1: BumpShield improves strict VRR over direct one-shot.
- H2: BumpShield improves strict VRR over direct retry, especially for
  transitive failures.
- H3: BumpShield improves root-cause localization on transitive failures.
- H4: BumpShield may produce smaller patches because its context is more
  targeted.
- H5: BumpShield may require fewer attempts where evidence directly identifies
  the API break.

These are pre-registered hypotheses, not expected or guaranteed outcomes.

## Strategies and budgets

- `direct-one-shot`: one provider attempt; target upgrade, bounded failure,
  localized source, and safety constraints only.
- `direct-retry`: up to three attempts; same initial context plus feedback from
  its own prior compile, test, patch, and safety results.
- `bumpshield`: up to three attempts; complete deterministic dependency, API,
  diagnosis, and migration-planning context.

All strategies use the same provider contract, timeout, fresh updated-commit
worktrees, patch analyzer, Maven execution, dependency guards, test-integrity
checks, and independent verifier.

## Scheduling

Strategy order follows `counterbalanced-rotation-v1`. Order rotates by case and
trial, so no strategy is systematically first or last. Execution positions are
persisted. One trial per case and strategy is frozen for the initial evaluation;
a later replication may pre-register three trials but must use a new frozen
configuration.

## Dataset

The target is 20 unseen cases: 10 direct and 10 transitive. At least 8–10 should
be defensible real-project cases when feasible. Remaining cases may be controlled
synthetic fixtures. The set should cover removed methods, changed signatures,
removed classes, removed packages, and removed dependencies without forcing an
artificially equal distribution.

Cases should vary in topology, call-site count, source usage, tests, and migration
shape. Twenty renamings of one fixture are not acceptable. Every case records
source, split, target transition, direct/transitive type, and defensible ground
truth. Partial or uncertain real-project labels are omitted from accuracy
denominators rather than guessed.

## Validity and verification

A valid case has an existing repository and commits, base tests passing, updated
tests failing, and the declared target old/new versions resolving correctly.
Invalid cases are explicit and excluded from repair denominators.

Only `VERIFIED_MIGRATION` counts as repair success. The requested dependency and
constrained causal dependency must remain upgraded; compile and tests must pass;
tests must remain present, enabled, and unskipped; patch safety and scope must be
acceptable. Provider prose never verifies a repair.

## Metrics

Strict VRR is primary:

```text
verified migrations / valid attempted trials
```

Provider failures remain in this denominator. Provider-available VRR is a
secondary operational metric and never replaces strict VRR. Reports also include
direct/transitive VRR, root-cause dependency and API accuracy, repair,
verification, provider and infrastructure failures, provider calls per verified
repair, attempts, total runtime, time to verified repair, and verified-patch
size.

Results are descriptive. Statistical significance is not claimed without a
separately justified sample size and analysis.

## Provider failure and resume policy

One attempted provider failure remains historical evidence. A clear global
quota, authentication, executable, or service failure pauses the run and leaves
later trials unexecuted. Resume preserves completed and failed rows, warns on
provider CLI version drift, rejects frozen model/prompt/policy drift, and
continues unexecuted rows. Rerunning an attempted trial requires explicit
`--rerun` and must be reported separately.

For 20 cases, three strategies, and one trial, maximum provider calls are 140:
20 direct one-shot, 60 direct retry, and 60 BumpShield calls.

## Unseen-case policy

Final cases are split `FINAL` and are not used for parser, prompt, causal-weight,
candidate-ranking, verifier, or manual repair-rule tuning. If an unseen case
reveals a genuine defect, record the incident, version the implementation and
frozen configuration, and rerun the complete evaluation rather than only failed
cases. Never silently alter `final-config-v1.json` after observing results.

## Interpretation

Report all cases and operational failures honestly. Separate development results
from unseen results. Do not remove cases because a strategy loses, do not weaken
the baseline, and do not reveal benchmark ground truth in any provider prompt.
