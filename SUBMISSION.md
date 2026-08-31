# BumpShield — Hackathon Submission

## One-sentence pitch

BumpShield is a Java/Maven dependency-migration agent that explains the causal
dependency and API change behind a broken upgrade, constrains an AI repair to a
reviewable scope, and independently proves the patch by compiling and testing it.

## User and bottleneck

The intended user is a Java maintainer, dependency-update owner, or platform
engineer whose project stopped building after a Maven dependency upgrade. The
bottleneck is not merely editing the compiler error: the changed direct
dependency can alter a transitive artifact, so the broken API, causal dependency
path, safe migration boundary, and behavioral validity all have to be recovered.

## Baseline and advanced solution

| System | Information available | Attempts | Acceptance rule |
|---|---|---:|---|
| **Baseline: Direct One-Shot** | Upgrade, bounded failure, source context | 1 | Same independent verifier |
| **Matched baseline: Direct Retry** | Same limited context plus execution feedback | Up to 3 | Same independent verifier |
| **Advanced: BumpShield** | Dependency diff, JAR/API evidence, causal diagnosis, migration plan | Up to 3 | Same independent verifier |

All three strategies are evaluated on the same cases. A model cannot award
itself success; only `VERIFIED_MIGRATION` from the independent verifier counts.

## Biggest contribution

BumpShield turns a repair suggestion into an auditable causal workflow:

```text
Reproduce -> Dependency Diff -> Failure -> API Evidence
          -> Diagnosis -> Plan -> AI Repair -> Independent Verification
```

The model edits only a disposable Git worktree. Git supplies patch ground
truth, while Maven execution, dependency guards, test-integrity checks,
test-skip checks, and patch-scope checks decide whether the result is accepted.

## Measured evidence

The frozen `BUMP-FINAL-v1` evaluation used 20 unseen synthetic cases, three
strategies, 60 independently verified trials, counterbalanced scheduling, and a
frozen configuration.

| Strategy | Strict verified repair rate | Direct | Transitive |
|---|---:|---:|---:|
| Direct One-Shot | 20/20 (100%) | 10/10 | 10/10 |
| Direct Retry | 20/20 (100%) | 10/10 | 10/10 |
| BumpShield | 18/20 (90%) | 9/10 | 9/10 |

BumpShield's two failures were provider quota failures and remain in the strict
denominator. Provider-available VRR was 18/18. Its causal dependency accuracy
was 20/20, including 10/10 transitive cases; exact API-change accuracy was
12/20. The experiment did **not** show a repair-rate advantage for causal
analysis. It did show complete causal dependency localization and preserved a
structured diagnosis, plan, patch, and verifier record for every available
repair.

The separate BoneCP showcase applies a constructed Guava 15-to-21 upgrade to
genuine Apache-licensed open-source source. BumpShield localized two removed
API uses, generated a two-file +4/-4 patch, and independently passed compilation
and 197 tests. It is real-world demonstration evidence, not an extra benchmark
case and not part of the rates above.

## What changed during the challenge

Before the challenge, there was no pre-existing BumpShield implementation or
evaluation result in this workspace. During the challenge the project gained
the deterministic investigation pipeline, bounded Codex repair, independent
verification, frozen comparative evaluation, provider pause/resume behavior,
offline replay GUI, and real-world BoneCP showcase. See the
[Improvement Changelog](docs/improvement-changelog.md) for decisions and
evidence.

## Removed experiment

The judge experience initially depended on a live provider-backed repair. That
live-only default was removed after quota failures showed it was operationally
fragile. The default demonstration is now an integrity-checked replay of a real
verified run; live mode remains explicitly optional and never fabricates a
result.

## Main failure mode and hot take

The main failure mode is provider availability: two otherwise valid final
trials and an earlier BoneCP attempt were interrupted by quota. BumpShield
records those failures instead of turning them into repair failures or silently
rerunning them.

**Hot take:** an agent should never grade its own patch. A smaller, externally
verified result is more valuable than a confident success message, and a fair
baseline that beats the proposed system is evidence to preserve rather than a
prompt-tuning opportunity.

## Reproduce and review

- [Clean-environment reproduction guide](docs/reproduction-guide.md)
- [CLI and GUI usage guide](docs/usage-guide.md)
- [Five-minute video script](docs/video-script.md)
- [Recorded video](https://drive.google.com/file/d/16wg-Q1MrWquszqIpJq8O4qjMoAHLgVvm/view?usp=sharing)
- [Representative agent trajectories](submission/agent-trajectories/README.md)
- [Agent instructions and boundaries](submission/agent-instructions/README.md)
- [Frozen final results](docs/final-research-results.md)
- [BoneCP real-world evidence](docs/real-world-showcase.md)
- [Architecture and safety boundary](docs/architecture.md)
- [Submission checklist](docs/submission-checklist.md)
- [Copy-ready submission form text](docs/submission-form-copy.md)

## Tool and data disclosure

- Codex was the coding agent used to build the project and the repair provider
  used in provider-backed runs.
- BumpShield's reproduction, dependency analysis, evidence collection,
  diagnosis, planning, patch analysis, and verification stages are
  deterministic Python/Git/Java/Maven code, not hidden LLM agents.
- `BUMP-FINAL-v1` uses challenge-authored synthetic fixtures.
- The separate BoneCP showcase identifies its public repository, upstream
  commit, Apache-2.0 license, build adaptations, and constructed upgrade.
- No credentials, provider tokens, private repositories, cloned upstream
  source, Maven cache, or raw provider account data are included.

## Submission artifacts

Run `python3 scripts/build_submission_archive.py` to create the sanitized ZIP
outside the repository. Source is published at
`https://github.com/FadyYosry77/BumpShield`; the current video is linked above
and embedded when the archive is built with `--video`. Repository visibility
and final platform submission remain human-controlled actions. The current
recording is approximately 6:37 and therefore must be shortened to satisfy the
stated five-minute limit.
