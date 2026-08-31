# BumpShield

> BumpShield finds why a dependency upgrade broke your project, repairs the
> migration, and proves the fix by execution.

BumpShield is a causal dependency migration agent for Java/Maven projects.
Instead of asking a coding model to repair an upgraded project blindly,
BumpShield reconstructs the dependency change, localizes the failure, inspects
old and new APIs, builds an explicit causal diagnosis, plans a bounded
migration, lets Codex propose a patch, and independently verifies the result.

**Hackathon reviewers:** start with the [submission overview](SUBMISSION.md),
then follow the [clean reproduction guide](docs/reproduction-guide.md). It
clearly separates the Direct One-Shot baseline, matched Direct Retry baseline,
advanced BumpShield workflow, frozen synthetic evaluation, and real-world
BoneCP showcase.

## Why BumpShield exists

A direct dependency upgrade can break project source through a different,
transitive artifact. A compiler error identifies the failing use but not the
dependency path or API change that caused it. BumpShield joins those facts into
an auditable chain before repair:

```text
core-lib 1.0 -> 2.0
        |
        +-- parser-lib 1.0 -> 2.0
                    |
                    +-- Parser.parseValue(String) removed
                                |
                                +-- TextNormalizer.java still calls it
                                            |
                                            +-- compilation failure
```

## How it works

```text
Reproduce
    |
Dependency Diff
    |
Failure Localization
    |
API Evidence
    |
Causal Diagnosis
    |
Migration Plan
    |
Constrained Repair
    |
Independent Verification
```

All stages except source repair are deterministic. Codex is used only to
propose edits inside an isolated repair worktree. Git, Maven, dependency
resolution, patch analysis, and the independent verifier decide whether the
result is accepted. See [architecture](docs/architecture.md).

## Core guarantees

**No green claim without green execution.** The repair model cannot certify
its own patch. `VERIFIED_MIGRATION` requires BumpShield to confirm:

- requested target dependency remains upgraded;
- constrained causal dependency was not downgraded;
- compilation passes;
- tests pass and still execute;
- tests were not deleted or newly disabled;
- patch scope and protected-file checks pass.

The original repository is never edited. BumpShield creates detached temporary
worktrees from the requested commits, exports successful patches to external
state, and removes repair worktrees afterward. It does not apply patches to the
original repository, commit, push, or create pull requests.

## Prerequisites

- Python 3.11+
- Git
- JDK with `javap`
- Maven or a project Maven wrapper
- Codex CLI for `repair` and provider-backed benchmarks

Deterministic unit tests require only Python and Git. Analysis commands use the
tools needed by their stage; Codex is not required until repair.

Successful integration and final evaluation used this tested environment:

- Python 3.12.3
- Git 2.43.0
- Eclipse Temurin Java 21.0.12.1
- Maven 3.9.16
- Codex CLI 0.151.0

Codex CLI 0.132.0 could not use the smoke-test model in the tested host;
upgrading to 0.151.0 resolved that compatibility issue. This is a tested
environment note, not a universal minimum-version claim.

## Quick start

For complete CLI, GUI, offline replay, artifact, and troubleshooting
instructions, see the [usage guide](docs/usage-guide.md).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
bumpshield --help
```

For development:

```bash
python -m pip install -e '.[dev]'
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider
```

## Demo GUI

The local Streamlit presentation layer provides two clearly labeled modes over
the same BumpShield evidence model:

- **Recorded Verified Run** is the default, reliable judge flow. It validates
  SHA-256 hashes for a small committed artifact bundle from a real verified
  Java/Maven/Codex run, then presents the recorded stages without invoking
  Codex, Maven, Java, Git analysis, the network, or repair execution.
- **Live Run** preserves the Phase 11 workflow over existing BumpShield
  services. Investigation and repair execute only after explicit button
  actions.

```bash
python -m pip install -e '.[demo]'
streamlit run demo_ui/app.py
```

Replay Mode does not simulate a new repair. It visualizes integrity-checked
evidence from an actual previously verified run and remains visibly labeled
`RECORDED VERIFIED RUN`. Live Mode provides the task form, causal investigation,
migration plan, explicit isolated repair, attempt timeline, Git-ground-truth
patch, and independent verification. Frozen research results remain read-only.
The CLI remains fully supported. See the [GUI judge walkthrough](docs/demo.md).

### Real-world open-source showcase

The replay selector also includes a verified BoneCP migration built from
genuine upstream open-source Java/Maven source. Its Guava `15.0` to `21.0`
change is a **constructed upgrade**, clearly separate from `BUMP-FINAL-v1`.
It must not be counted in the frozen benchmark's 20 cases or reported rates.
See the [BoneCP evidence and limitations](docs/real-world-showcase.md).

## Task format

Create `task.json`:

```json
{
  "repository": "/path/to/project",
  "base_commit": "<working-commit>",
  "updated_commit": "<upgraded-commit>",
  "target_dependency": {
    "group_id": "org.example",
    "artifact_id": "library",
    "old_version": "1.0.0",
    "new_version": "2.0.0"
  }
}
```

`repository` may be absolute or relative to `task.json`. Both commits must
exist in that Git repository.

## Commands

| Command | Purpose |
|---|---|
| `bumpshield reproduce task.json` | Prove base passes and updated revision fails. |
| `bumpshield dependencies task.json` | Compare resolved Maven dependency graphs. |
| `bumpshield failures task.json` | Parse and safely localize updated-revision failures. |
| `bumpshield evidence task.json` | Attribute classes to JARs and compare public APIs with `javap`. |
| `bumpshield diagnose task.json` | Build deterministic causal hypotheses. |
| `bumpshield plan task.json` | Produce bounded migration scope, constraints, and candidate APIs. |
| `bumpshield repair task.json` | Run the complete constrained repair and verification workflow. |
| `bumpshield benchmark suite.json` | Evaluate repair strategies with the same verifier. |

Use `--state-dir /external/path` on analysis, repair, and benchmark commands to
control persistent state location. Main demo command:

```bash
bumpshield repair task.json --state-dir /tmp/bumpshield-state
```

See the copyable [3–5 minute demo](docs/demo.md).

## Evidence and run artifacts

Runs persist outside the analyzed repository:

```text
state/
└── runs/<run-id>/
    ├── dependency-diff.json
    ├── failures.json
    ├── api-evidence.json
    ├── causal-diagnosis.json
    ├── migration-plan.json
    ├── repair-context.json
    ├── attempts/
    ├── final.patch
    └── migration-report.txt
```

Unavailable or non-actionable evidence remains explicit. New API candidates in
a migration plan are evidence for repair reasoning, not guaranteed semantic
replacements.

## Security and isolation

- All commands run through the centralized `CommandRunner`; no `shell=True` is
  used.
- Repository-relative paths are normalized and checked against traversal and
  escaping symlinks.
- JARs are inspected as ZIP archives and with bounded `javap` calls; their code
  is not executed by the evidence collector.
- State and raw artifacts stay outside source repositories.
- Git diff, not provider claims, determines actual modifications.
- Dependency, test-integrity, test-skip, and patch-scope guards run before final
  acceptance.
- No patch is automatically applied, committed, pushed, or published.

## Integration proof

The end-to-end pipeline reached `VERIFIED_MIGRATION` on a real local transitive
fixture using real Git, Java, Maven, JARs, `javap`, Codex, compilation, tests,
and independent verification. This proves integration for one controlled case,
not broad production reliability. See the
[integration smoke report](docs/integration-smoke-report.md).

## Evaluation methodology

Every strategy uses the same independent verifier. Strict Verified Repair Rate
(VRR) counts all valid attempted trials, including provider failures.
Provider-available VRR excludes provider-unavailable trials and is reported only
as a secondary operational metric.

- **Direct One-Shot:** bounded build failure and source context, one attempt,
  no BumpShield causal evidence.
- **Direct Retry:** same limited context, up to three attempts with execution
  feedback.
- **BumpShield:** up to three attempts with dependency diff, JAR/API evidence,
  causal diagnosis, and migration plan.

Strategy order was counterbalanced under a frozen configuration. Full protocol,
case-construction plan, and results are available in
[evaluation protocol](docs/evaluation-protocol.md),
[final benchmark plan](docs/final-benchmark-plan.md), and
[final research results](docs/final-research-results.md).

## BUMP-FINAL-v1 results

BUMP-FINAL-v1 contains **20 synthetic fixtures and 0 real-project cases**. It
ran one trial for each of three strategies: 60 independently scored trials.

| Strategy | Verified | Strict VRR |
|---|---:|---:|
| Direct One-Shot | 20/20 | 100% |
| Direct Retry | 20/20 | 100% |
| BumpShield | 18/20 | 90% |

| Strategy | Direct | Transitive |
|---|---:|---:|
| Direct One-Shot | 10/10 | 10/10 |
| Direct Retry | 10/10 | 10/10 |
| BumpShield | 9/10 | 9/10 |

Additional BumpShield results:

- provider-available VRR: 18/18 (100%);
- causal dependency localization: 20/20 (100%);
- transitive dependency localization: 10/10 (100%);
- exact API-change accuracy: 12/20 (60%);
- supported diagnosis and ready plan: 20/20;
- ordinary final repair, dependency-guard, test-integrity, test-skip, patch-scope,
  and final compile/test failures: 0.

BumpShield's two strict-VRR failures were Codex quota failures. They remain in
the strict denominator and were not rewritten as repair successes.

### Research interpretation

The frozen synthetic benchmark did **not** show a verified repair-rate advantage
for explicit causal analysis. All provider-available repair trials succeeded
across all three strategies. BumpShield's strongest measured result was
diagnostic: it independently localized the causal dependency in every case,
including all transitive cases, while preserving an auditable diagnosis,
migration plan, repair boundary, and verification record.

Broader repair-rate benefits remain unproven. Production generality requires
evaluation on real open-source projects. The lightweight frozen result snapshot
is under [`benchmark/results/BUMP-FINAL-v1/`](benchmark/results/BUMP-FINAL-v1/).
BUMP-DEV remains separate development evidence; see
[benchmark documentation](benchmark/README.md).

## Repository structure

```text
bumpshield/                 Python package
  agent/                    diagnosis, planning, provider, repair orchestration
  analysis/                 regression, dependency, failure, API, patch analysis
  evaluation/               frozen benchmark loading, scheduling, metrics, reports
  execution/                command, Maven, javap, independent verification
  repo/                     Git and worktree isolation
  report/                   human-readable run reports
tests/                      deterministic unit and integration-boundary tests
benchmark/                  manifests, fixture sources, preparation, result snapshot
demo_ui/                    Streamlit presentation and typed view adapters
integration-fixtures/       real-tool smoke fixture sources
docs/                       architecture, demo, protocol, and research reports
```

## Limitations

- Java and Maven only; Gradle and other ecosystems are unsupported.
- One Maven project root per analysis; multi-module/reactor support is limited.
- Failure parsing targets common Javac and Surefire formats, not every plugin.
- Java usage discovery is conservative lexical search, not full symbol
  resolution.
- API comparison uses public `javap` declarations; generics and varargs remain
  basic.
- Behavioral failures without concrete API evidence are harder to diagnose.
- Existing project tests are the behavioral oracle; BumpShield does not prove
  semantic equivalence.
- BUMP-FINAL-v1 contains only synthetic fixtures and one trial per
  case/strategy.
- External Codex availability and quota affect operational reliability.

## Future work

- frozen real open-source benchmark cases;
- multi-module Maven and Gradle support;
- upstream documentation and semantic migration evidence;
- behavioral regression analysis and generated regression tests;
- repeated model trials and ambiguous-diagnosis assistance;
- optional reviewed patch or pull-request workflows.

## Portfolio summary

Built an agentic Java/Maven dependency-migration system that reproduces
dependency regressions, reconstructs transitive causal chains, compares JAR APIs
with `javap`, constrains Codex repairs, and independently verifies generated
migrations. Evaluated it on a frozen 20-case synthetic benchmark with three
repair strategies and 60 independently scored trials.

## Main failure mode and hot take

Provider availability is the main operational failure mode: two final
BumpShield trials ended in quota failures and remain in strict VRR. The
live-only demo was therefore replaced as the default by integrity-checked
recorded replay of an actual verified run.

**Hot take:** an agent should never grade its own patch. A fair baseline that
wins and a verifier-controlled failure are more useful than a confident model
claim. See the [Improvement Changelog](docs/improvement-changelog.md).

## License

No `LICENSE` file is currently included. The project owner must select a license
before public distribution.

## Project documentation

- [Hackathon submission overview](SUBMISSION.md)
- [Clean-environment reproduction](docs/reproduction-guide.md)
- [Improvement changelog](docs/improvement-changelog.md)
- [Five-minute video script](docs/video-script.md)
- [Representative agent trajectories](submission/agent-trajectories/README.md)
- [Agent instructions and boundaries](submission/agent-instructions/README.md)
- [Submission checklist](docs/submission-checklist.md)
- [Project goal and source of truth](BumpShield_PROJECT_GOAL.md)
- [Architecture](docs/architecture.md)
- [Live demo](docs/demo.md)
- [Integration smoke report](docs/integration-smoke-report.md)
- [Evaluation protocol](docs/evaluation-protocol.md)
- [Final benchmark plan](docs/final-benchmark-plan.md)
- [Final research results](docs/final-research-results.md)
