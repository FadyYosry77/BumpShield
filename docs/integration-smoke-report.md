# Phase 7.1 real integration smoke report

Date: 2026-08-29

## Outcome

BumpShield completed a real transitive Java/Maven dependency migration and
returned `VERIFIED_MIGRATION`. The run used real Git worktrees, Maven dependency
resolution, compiled JARs, `javap`, the local Codex CLI, Maven compilation,
Maven tests, and BumpShield's independent verifier. No fake runner participated
in the final run.

Final run ID: `e8da6b87cfff4fbda06cc7ff1697f3f2`

## Environment

- Python: 3.12.3
- Git: 2.43.0
- Java/Javac/Javap: Eclipse Temurin 21.0.12.1 LTS
- Maven: 3.9.16
- Codex CLI before smoke setup: 0.132.0
- Codex CLI used by the successful run: 0.151.0

Java and Maven were installed in a disposable user-local tool directory because
the host did not provide them and passwordless package installation was not
available. Maven used a disposable custom local repository, which also verified
that BumpShield does not assume `~/.m2/repository`.

## Fixture

The fixture is stored under `integration-fixtures/phase7_1/` and has this
dependency path:

```text
application
└── core-lib 1.0.0 -> 2.0.0
    └── parser-lib 1.0.0 -> 2.0.0
```

The application directly upgrades `com.bumpshield.fixture:core-lib` and uses
`Parser` from transitive `parser-lib`. Parser 1.0.0 provides
`parseValue(String)`. Parser 2.0.0 replaces it with
`parse(String, ParserOptions)` and exposes `ParserOptions.DEFAULT`.

- Base commit: `5471be4c348efac00c9cfc0462bb8506ffeb442c`
- Updated commit: `471057fc3a87e32a7c7554b5446fd6bbf35f0532`
- Base `mvn -B test`: PASS, 3 tests, 0 failures/errors/skips
- Updated `mvn -B test`: FAIL on real missing `parseValue(String)` compilation

The three JUnit tests verify trimming outer whitespace, preserving inner
whitespace, and handling whitespace-only input. A constant or deleted call
cannot satisfy all cases.

## Pipeline evidence

- Reproduction: `CONFIRMED`; base PASS, updated FAIL.
- Dependency analysis: target `core-lib 1.0.0 -> 2.0.0`; transitive
  `parser-lib 1.0.0 -> 2.0.0`.
- Failure localization: `MISSING_SYMBOL` at
  `src/main/java/com/bumpshield/fixture/app/TextNormalizer.java:9`, symbol
  `parseValue(java.lang.String)`.
- API evidence: exact class owner `parser-lib`; real old/new JARs inspected;
  `javap -public` established `REMOVED_MEMBER`.
- Dependency provenance: `core-lib:2.0.0 -> parser-lib:2.0.0`.
- Diagnosis: `SUPPORTED_DIAGNOSIS`, `VERY_STRONG`, 100/100 ordinal evidence
  score.
- Plan: `PLAN_READY`, `REMOVED_METHOD`, one bounded allowed source file, new
  API candidate retained as unverified migration evidence.
- Codex repair: one real attempt.
- Patch: one file, 2 lines added, 1 line removed.
- Independent compile: PASS.
- Independent tests: PASS, 3 tests, 0 failures/errors/skips.
- Dependency guards: target 2.0.0 retained; causal transitive 2.0.0 retained.
- Test integrity, test execution, patch scope, and patch safety: PASS.
- Final status: `VERIFIED_MIGRATION`.

The winning patch imports `ParserOptions` and replaces
`parser.parseValue(value)` with `parser.parse(value, ParserOptions.DEFAULT)`.
It does not change the POM, tests, or unrelated files.

## Repository isolation

Before and after repair, the analyzed repository remained at updated commit
`471057fc3a87e32a7c7554b5446fd6bbf35f0532`. Git status remained exactly
`?? user-note.txt`, and hashes of the POM, production source, test source, and
the untracked sentinel were identical. `git worktree list` contained only the
original repository after completion. The winning patch persisted only in the
external run directory as `final.patch`.

## Integration hardening

The system Codex CLI 0.132.0 could not use the configured `gpt-5.6-sol` model,
so the smoke environment installed Codex CLI 0.151.0 without changing the
configured model. Current `codex exec` help was inspected before use.

Real provider output also showed host customization being considered during an
isolated repair. `CodexRepairProvider` now invokes `codex exec` with
`--ignore-user-config`, `--ignore-rules`, and disabled dynamic skill search.
Those switches are subcommand options and therefore must occur after `exec`;
a regression test locks that real CLI ordering. Workspace-write sandboxing and
independent Git inspection remain the authority for write isolation.

## Known limitations

- This is one local smoke fixture, not benchmark or production-reliability
  evidence.
- Host/system instructions may still mention preloaded skills even when dynamic
  skill search and user configuration are disabled. The enforced guarantee is
  that project edits remain inside the repair worktree; local build/toolchain
  reads remain available so Maven and `javap` can function.
- Java, Maven, fixture artifacts, and upgraded Codex CLI were installed in a
  disposable directory and are not runtime dependencies of the Python package.
- Normal pytest remains deterministic and does not execute Java, Maven, Codex,
  network, or this fixture.
