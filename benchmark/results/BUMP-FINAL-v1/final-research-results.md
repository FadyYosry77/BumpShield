# BUMP-FINAL-v1 research results

## Research question

Does explicit causal dependency analysis improve independently verified repair of breaking Java/Maven dependency upgrades?

## Executive summary

BUMP-FINAL-v1 did not show a verified repair-rate advantage for explicit
causal analysis. Direct One-Shot and Direct Retry each verified 20/20 cases;
BumpShield verified 18/20 under strict VRR and 18/18 when the provider was
available. Its two strict failures were Codex quota failures, not rejected
patches.

BumpShield's strongest observed result was diagnostic and procedural: it
localized the causal dependency in 20/20 cases, including all 10 transitive
cases, and produced a supported diagnosis plus ready migration plan for every
case. Exact API-change accuracy was 12/20. These results concern 20 controlled
synthetic fixtures and do not establish production-project generality.

## Frozen evaluation

- Configuration hash: `3c0dfaad58f985d1c9a9db7f17ee28a84af7f8b3bcce45de5dd078877943ff56`
- Dataset hash: `8bd13704194037bd3c672233af5d4e1102d78cb084aea736dd7738ded37a4e8a`
- Cases: 20 (10 direct, 10 transitive)
- Run: `299751febab64a96a891fd9f2f2954c9`
- Run status: `COMPLETED`
- Trials: 60/60 completed

## Strict Verified Repair Rate

| Strategy | Verified | Attempted | Strict VRR |
|---|---:|---:|---:|
| bumpshield | 18 | 20 | 90.0% |
| direct-one-shot | 20 | 20 | 100.0% |
| direct-retry | 20 | 20 | 100.0% |

Provider failures remain in strict VRR. Provider-available VRR below is secondary.

## Provider-available VRR

| Strategy | Verified | Available trials | VRR |
|---|---:|---:|---:|
| bumpshield | 18 | 18 | 100.0% |
| direct-one-shot | 20 | 20 | 100.0% |
| direct-retry | 20 | 20 | 100.0% |

## Direct cases

| Strategy | Verified | Attempted | Strict VRR |
|---|---:|---:|---:|
| bumpshield | 9 | 10 | 90.0% |
| direct-one-shot | 10 | 10 | 100.0% |
| direct-retry | 10 | 10 | 100.0% |

## Transitive cases

| Strategy | Verified | Attempted | Strict VRR |
|---|---:|---:|---:|
| bumpshield | 9 | 10 | 90.0% |
| direct-one-shot | 10 | 10 | 100.0% |
| direct-retry | 10 | 10 | 100.0% |

## Paired outcomes

### BumpShield vs Direct Retry

Both verified: 18; bumpshield only: 0; direct-retry only: 2; neither: 0; comparable pairs: 20.

### BumpShield vs Direct One-Shot

Both verified: 18; bumpshield only: 0; direct-one-shot only: 2; neither: 0; comparable pairs: 20.

### Transitive: BumpShield vs Direct Retry

Both verified: 9; bumpshield only: 0; direct-retry only: 1; neither: 0; comparable pairs: 10.


## Root-cause localization

- Dependency: 20/20 (100.0%)
- API change: 12/20 (60.0%)
- DIRECT: 10/10 (100.0%)
- TRANSITIVE: 10/10 (100.0%)

## Diagnosis and planning

- Diagnosis: SUPPORTED_DIAGNOSIS=20
- Plans: PLAN_READY=20

## Attempts, provider calls, runtime, and patch size

- bumpshield: attempts all mean/median 1.200/1.000; verified 1.000/1.000; calls 24; calls/verified 1.333; runtime all 83.891/88.220 s; verified time 88.534/89.508 s; verified files 1.000/1.000; verified patch 5.333/6.000 lines.
- direct-one-shot: attempts all mean/median 1.000/1.000; verified 1.000/1.000; calls 20; calls/verified 1.000; runtime all 90.551/86.618 s; verified time 90.551/86.618 s; verified files 1.000/1.000; verified patch 5.450/5.500 lines.
- direct-retry: attempts all mean/median 1.000/1.000; verified 1.000/1.000; calls 20; calls/verified 1.000; runtime all 88.564/87.611 s; verified time 88.564/87.611 s; verified files 1.000/1.000; verified patch 5.600/6.000 lines.

## Failure types

- CHANGED_METHOD_SIGNATURE: bumpshield=4/4 (100.0%), direct-one-shot=4/4 (100.0%), direct-retry=4/4 (100.0%)
- REMOVED_CLASS: bumpshield=4/4 (100.0%), direct-one-shot=4/4 (100.0%), direct-retry=4/4 (100.0%)
- REMOVED_DEPENDENCY: bumpshield=3/4 (75.0%), direct-one-shot=4/4 (100.0%), direct-retry=4/4 (100.0%)
- REMOVED_METHOD: bumpshield=3/4 (75.0%), direct-one-shot=4/4 (100.0%), direct-retry=4/4 (100.0%)
- REMOVED_PACKAGE: bumpshield=4/4 (100.0%), direct-one-shot=4/4 (100.0%), direct-retry=4/4 (100.0%)

## Case sources

- SYNTHETIC_FIXTURE / bumpshield: 18/20 (90.0%)
- SYNTHETIC_FIXTURE / direct-one-shot: 20/20 (100.0%)
- SYNTHETIC_FIXTURE / direct-retry: 20/20 (100.0%)

## Case-level outcomes

| Case | Type | Failure | Source | One-shot | Retry | BumpShield | Root cause correct | BumpShield attempts |
|---|---|---|---|---|---|---|---|---:|
| final-case-001 | DIRECT | REMOVED_METHOD | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | UNRESOLVED | True | 3 |
| final-case-002 | DIRECT | REMOVED_METHOD | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-003 | DIRECT | REMOVED_METHOD | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-004 | DIRECT | CHANGED_METHOD_SIGNATURE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-005 | DIRECT | CHANGED_METHOD_SIGNATURE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-006 | DIRECT | CHANGED_METHOD_SIGNATURE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-007 | DIRECT | REMOVED_CLASS | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-008 | DIRECT | REMOVED_CLASS | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-009 | DIRECT | REMOVED_PACKAGE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-010 | DIRECT | REMOVED_PACKAGE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-011 | TRANSITIVE | REMOVED_METHOD | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-012 | TRANSITIVE | CHANGED_METHOD_SIGNATURE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-013 | TRANSITIVE | REMOVED_CLASS | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-014 | TRANSITIVE | REMOVED_CLASS | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-015 | TRANSITIVE | REMOVED_PACKAGE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-016 | TRANSITIVE | REMOVED_PACKAGE | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-017 | TRANSITIVE | REMOVED_DEPENDENCY | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-018 | TRANSITIVE | REMOVED_DEPENDENCY | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |
| final-case-019 | TRANSITIVE | REMOVED_DEPENDENCY | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | UNRESOLVED | True | 3 |
| final-case-020 | TRANSITIVE | REMOVED_DEPENDENCY | SYNTHETIC_FIXTURE | VERIFIED_MIGRATION | VERIFIED_MIGRATION | VERIFIED_MIGRATION | True | 1 |

## Failure analysis

- bumpshield: provider=2, infrastructure=0, repair=0, verification=0; reasons PROVIDER_FAILED=2
- direct-one-shot: provider=0, infrastructure=0, repair=0, verification=0; reasons none
- direct-retry: provider=0, infrastructure=0, repair=0, verification=0; reasons none

## Research interpretation

On this frozen synthetic benchmark, explicit causal evidence improved the
audit trail but did not improve the measured verified repair rate. Both direct
strategies verified every case without receiving BumpShield's dependency diff,
JAR/API evidence, causal diagnosis, or migration plan. BumpShield nevertheless
identified every causal dependency and retained structured evidence from
regression through verification.

The result should therefore be read as evidence that the deterministic
investigation pipeline provides reliable localization and auditability on this
dataset, not as evidence of a repair-rate advantage. The experiment is
descriptive and does not support a claim that causal analysis always helps—or
never helps—dependency migration repair.

## Execution integrity

The provider circuit breaker paused twice on Codex quota exhaustion. Both
attempted BumpShield trials remain unresolved in the primary strict-VRR
denominator; neither was rerun.

An external orchestration failure also caused the temporary Java, Maven, Codex,
and Maven-repository paths to disappear after trial 33. Trials 34 through 60
were initially recorded as invalid without provider calls because Maven could
not execute. Those invalid rows and their reports remain archived in the
external audit bundle. The exact tool versions were restored under stable
external paths, the controlled Maven cache was rebuilt from frozen fixture
sources, and only affected invalid rows were replaced. Trials 1 through 33 were
not rerun. The replacement policy is preserved in
`benchmark/results/BUMP-FINAL-v1/infrastructure-rerun-policy.json`.

Post-run checks reconfirmed the configuration and dataset hashes, found no
ground-truth leakage in provider requests, found no tracked or index changes in
the 20 fixture repositories, and found no stale repair worktrees.

## Limitations

- All 20 cases are controlled synthetic fixtures; no real open-source project
  case appears in BUMP-FINAL-v1.
- Each case/strategy combination ran once, so the result does not estimate
  model-output variance.
- Two BumpShield trials encountered provider quota failures. Strict VRR keeps
  them in the denominator; provider-available VRR is secondary.
- Runtime and provider behavior depend on the tested environment.
- Existing project tests remain the behavioral oracle; no semantic equivalence
  proof is claimed.
- The 20-case sample supports descriptive comparison only. No statistical
  significance is claimed.
