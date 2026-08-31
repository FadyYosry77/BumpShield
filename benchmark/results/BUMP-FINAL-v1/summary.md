# BumpShield Benchmark Results

## Configuration

- Suite: `BUMP-FINAL-v1`
- Run: `299751febab64a96a891fd9f2f2954c9`
- Provider: `codex-cli`
- Maximum BumpShield attempts: 3

## Environment

- Platform: Linux-7.0.0-30-generic-x86_64-with-glibc2.39
- Python: 3.12.3 (main, Jun 19 2026, 12:46:00) [GCC 13.3.0]
- Git: git version 2.43.0
- Java: openjdk version "21.0.12.1" 2026-08-18 LTS
- Maven: Apache Maven 3.9.16 (2bdd9fddda4b155ebf8000e807eb73fd829a51d5)
- Codex: codex-cli 0.151.0

## Dataset

- Cases: 20
- Valid: 20
- Invalid: 0
- Run status: `COMPLETED`
- Planned trials: 60
- Attempted valid trials: 60
- Completed rows: 60
- Unexecuted trials: 0

## Overall Results

| Strategy | Verified | Attempted | Strict VRR | Provider failures |
|---|---:|---:|---:|---:|
| bumpshield | 18 | 20 | 90.0% | 2 |
| direct-one-shot | 20 | 20 | 100.0% | 0 |
| direct-retry | 20 | 20 | 100.0% | 0 |

Strict VRR is primary and includes attempted provider failures.

## Provider-Available VRR (Secondary)

| Strategy | Provider-available trials | Verified | Conditional VRR |
|---|---:|---:|---:|
| bumpshield | 18 | 18 | 100.0% |
| direct-one-shot | 20 | 20 | 100.0% |
| direct-retry | 20 | 20 | 100.0% |

## Direct Dependency Cases

| Strategy | Verified | Attempted | Strict VRR | Provider failures |
|---|---:|---:|---:|---:|
| bumpshield | 9 | 10 | 90.0% | 1 |
| direct-one-shot | 10 | 10 | 100.0% | 0 |
| direct-retry | 10 | 10 | 100.0% | 0 |

## Transitive Dependency Cases

| Strategy | Verified | Attempted | Strict VRR | Provider failures |
|---|---:|---:|---:|---:|
| bumpshield | 9 | 10 | 90.0% | 1 |
| direct-one-shot | 10 | 10 | 100.0% | 0 |
| direct-retry | 10 | 10 | 100.0% | 0 |

## Root Cause Localization

BumpShield dependency accuracy: 20/20 (100.0%).
BumpShield API-change accuracy: 12/20 (60.0%).
bumpshield diagnosis success rate: 100.0%.

## Comparative Metrics

BumpShield minus direct-one-shot VRR: -10.0 percentage points
BumpShield minus direct-one-shot mean attempts: 0.200
BumpShield minus direct-one-shot mean patch size: -0.650
BumpShield minus direct-one-shot mean runtime seconds: -6.660
BumpShield minus direct-retry strict VRR: -10.0 percentage points
Direct-retry minus direct-one-shot strict VRR: +0.0 percentage points

## Repair Attempts

- bumpshield: mean 1.200, median 1.000
- direct-one-shot: mean 1.000, median 1.000
- direct-retry: mean 1.000, median 1.000

Verified repairs only:
- bumpshield: mean 1.000, median 1.000
- direct-one-shot: mean 1.000, median 1.000
- direct-retry: mean 1.000, median 1.000

## Runtime

- bumpshield: mean 83.891, median 88.220
- direct-one-shot: mean 90.551, median 86.618
- direct-retry: mean 88.564, median 87.611

Time to verified repair:
- bumpshield: mean 88.534, median 89.508
- direct-one-shot: mean 90.551, median 86.618
- direct-retry: mean 88.564, median 87.611

Diagnosis/planning runtime (BumpShield only where available):
- bumpshield: mean 8.113, median 8.105
- direct-one-shot: mean n/a, median n/a
- direct-retry: mean n/a, median n/a

## Patch Size

- bumpshield: mean 4.800, median 4.500
- direct-one-shot: mean 5.450, median 5.500
- direct-retry: mean 5.600, median 6.000

Verified repairs only:
- bumpshield: mean 5.333, median 6.000
- direct-one-shot: mean 5.450, median 5.500
- direct-retry: mean 5.600, median 6.000

## Provider and Infrastructure

- bumpshield: calls=24, calls/verified=1.333, provider failures=2, quota=2, timeouts=0, unknown=0, provider failure rate=10.0%
- direct-one-shot: calls=20, calls/verified=1.000, provider failures=0, quota=0, timeouts=0, unknown=0, provider failure rate=0.0%
- direct-retry: calls=20, calls/verified=1.000, provider failures=0, quota=0, timeouts=0, unknown=0, provider failure rate=0.0%

## Failure Domains

- bumpshield: repair=0, verification=0, provider=2, infrastructure=0, repair failure rate=0.0%, infrastructure failure rate=10.0%
- direct-one-shot: repair=0, verification=0, provider=0, infrastructure=0, repair failure rate=0.0%, infrastructure failure rate=0.0%
- direct-retry: repair=0, verification=0, provider=0, infrastructure=0, repair failure rate=0.0%, infrastructure failure rate=0.0%

## Failure Analysis

- bumpshield: PROVIDER_FAILED=2
- direct-one-shot: none
- direct-retry: none

## Limitations

These are descriptive results. Development fixtures are not an unseen final dataset, model output may vary, and small samples do not establish statistical significance.
