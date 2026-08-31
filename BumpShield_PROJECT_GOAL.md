# BumpShield — Project Goal and Build Contract

> **This file is the source of truth for the project.**
>
> Every coding session, Codex task, implementation decision, refactor, and feature addition must remain consistent with this document.
>
> If a proposed implementation conflicts with this file, this file wins.

---

# 1. Project Name

## BumpShield

### Causal Dependency Migration Agent

---

# 2. One-Line Project Goal

> **BumpShield diagnoses why a dependency upgrade broke a previously working software project, reconstructs the causal chain behind the regression, produces the smallest appropriate migration, and accepts the repair only when real execution verifies that the upgraded project builds and passes its tests.**

---

# 3. The Problem We Are Solving

Modern software projects rely on many external dependencies.

Tools such as Dependabot and Renovate can automatically propose dependency upgrades, but upgrading a dependency can cause:

- compilation failures
- test failures
- removed APIs
- changed method signatures
- changed configuration behavior
- transitive dependency upgrades
- runtime incompatibilities
- unexpected behavioral regressions

A maintainer may see an error such as:

```text
cannot find symbol: method parseValue(String)
```

but that error only shows **where the project broke**.

It does not necessarily show **why it broke**.

The actual causal chain may look like:

```text
Project
   ↓
Direct dependency A upgraded
   ↓
Transitive dependency B upgraded
   ↓
B removed or changed API X
   ↓
Project still calls API X
   ↓
Compilation or tests fail
```

Today a developer often has to manually:

```text
reproduce the regression
↓
inspect build logs
↓
compare dependency versions
↓
compare dependency graphs
↓
inspect transitive dependencies
↓
locate affected project code
↓
inspect old and new APIs
↓
read migration evidence
↓
guess a root cause
↓
modify code
↓
build again
↓
run tests
↓
repeat
```

BumpShield automates this investigation and repair loop.

---

# 4. Core Research Idea

BumpShield is based on the following hypothesis:

> **Dependency-repair agents often fail because they react to downstream compiler or test errors without first identifying the upstream dependency change that actually caused the regression.**

A conventional repair workflow is often:

```text
error
↓
guess patch
```

BumpShield instead follows:

```text
error
↓
investigate
↓
collect evidence
↓
identify likely cause
↓
plan migration
↓
repair
↓
execute
↓
verify
```

The important distinction is:

> **BumpShield performs causal diagnosis before repair.**

---

# 5. Primary Research Question

> **Can explicit causal analysis of dependency changes improve automated repair of breaking dependency upgrades compared with a conventional LLM that receives the failure and immediately attempts to patch the code?**

The system should eventually make it possible to compare:

```text
LLM sees error → generates patch
```

against:

```text
BumpShield
dependency analysis
+ failure localization
+ API evidence
+ causal hypothesis
+ repair
+ execution
+ verification
```

---

# 6. Exact MVP Scope

The first BumpShield prototype is intentionally narrow.

## Supported ecosystem

```text
Java
+
Maven
```

## Supported task

A task contains:

```text
one repository
+
one known working revision
+
one broken post-upgrade revision
+
one known dependency upgrade
+
a reproducible build or test regression
```

The MVP does **not** need to support arbitrary repositories or languages.

The goal is depth and reliability within this narrow scope.

---

# 7. Required Input

A BumpShield task should contain at least:

```json
{
  "repository": "/path/to/repository",
  "base_commit": "abc123",
  "updated_commit": "def456",
  "target_dependency": {
    "group_id": "org.example",
    "artifact_id": "foo",
    "old_version": "2.8.0",
    "new_version": "3.0.0"
  }
}
```

Optional information may include:

- CI logs
- build logs
- test failures
- pull request metadata
- migration notes
- dependency manifest changes

However:

> **BumpShield must gather and verify its own evidence rather than blindly trust descriptions supplied in the task.**

---

# 8. Required End-to-End Workflow

The MVP workflow is:

```text
Task
↓
1. Reproduce regression
↓
2. Compare dependency resolution
↓
3. Localize failure
↓
4. Collect relevant API/source evidence
↓
5. Construct causal hypothesis
↓
6. Generate minimal migration
↓
7. Execute build/tests
↓
8. Use failures as new evidence if necessary
↓
9. Independently verify the result
↓
10. Produce migration report
```

Every major implementation decision should support this pipeline.

---

# 9. Phase 1 — Regression Reproduction

BumpShield must first establish that the dependency update actually corresponds to a regression.

It must run the project at the working revision and verify:

```text
BASE REVISION

build/tests → PASS
```

Then run the updated revision:

```text
UPDATED REVISION

build/tests → FAIL
```

The valid causal setup is:

```text
old revision ✅
new revision ❌
```

If both fail:

```text
old revision ❌
new revision ❌
```

BumpShield should not pretend the dependency update caused the problem.

Possible result:

```text
INVALID_CASE
```

or an equivalent structured status.

---

# 10. Phase 2 — Dependency Change Analysis

BumpShield must determine what changed in Maven dependency resolution.

It should compare the dependency graph before and after the upgrade.

Example:

```text
BEFORE

A 2.8
└── B 4.6
```

```text
AFTER

A 3.0
└── B 5.0
```

The analyzer should report:

```text
Target dependency:
A 2.8 → 3.0

Transitive change:
B 4.6 → 5.0
```

This is essential because:

```text
dependency directly upgraded by the user
```

is not always equal to:

```text
dependency that actually introduced the breaking change
```

BumpShield must preserve this distinction.

---

# 11. Phase 3 — Failure Localization

BumpShield must parse compiler or test failures and identify relevant project locations.

Initial failure categories should include common Maven/Java cases such as:

```text
cannot find symbol

method cannot be applied

package does not exist

incompatible types

class not found

test failure

stack trace
```

The system should extract structured signals such as:

```json
{
  "category": "missing_method",
  "file": "src/main/java/example/FooParser.java",
  "line": 84,
  "symbol": "parseValue",
  "message": "cannot find symbol"
}
```

The system should then retrieve only relevant source context.

It should avoid sending the entire repository to the LLM when a small set of files and symbols is sufficient.

---

# 12. Phase 4 — Evidence Collection

BumpShield should collect evidence that helps explain the failure.

Potential evidence includes:

- before/after dependency graph
- changed transitive dependencies
- compiler or test failure
- affected project call site
- old dependency API
- new dependency API
- relevant source code
- migration documentation when useful
- release notes when useful
- upstream source changes when useful

Evidence collection should be targeted.

Bad approach:

```text
collect every possible document
```

Preferred approach:

```text
failure suggests missing method
↓
identify dependency containing that method
↓
compare old/new API
↓
collect only evidence needed to test the hypothesis
```

---

# 13. Phase 5 — Causal Hypothesis

Before editing source code, BumpShield must explain what it believes caused the regression.

Example:

```text
Target update:
foo-core 2.8 → 3.0

caused:

Transitive update:
foo-parser 4.6 → 5.0

which caused:

API change:
parseValue(String) removed

while:

Project file FooParser.java:84 still calls parseValue(String)

therefore:

Compilation fails.
```

The investigator should produce structured output similar to:

```json
{
  "root_cause": "foo-parser 5.0 removed parseValue(String)",
  "causal_chain": [
    "foo-core upgraded from 2.8.0 to 3.0.0",
    "foo-parser changed from 4.6.0 to 5.0.0",
    "parseValue(String) is absent from foo-parser 5.0.0",
    "FooParser.java:84 still calls parseValue(String)"
  ],
  "confidence": 0.91,
  "supporting_evidence": [
    "dependency_diff",
    "compiler_failure",
    "api_diff",
    "source_call_site"
  ]
}
```

Confidence is secondary.

The important requirement is:

> **The hypothesis must name a concrete cause and point to evidence supporting it.**

---

# 14. Phase 6 — Migration Planning

Only after investigation should BumpShield plan the repair.

The migration planner receives:

```text
causal hypothesis
+
affected source locations
+
new API evidence
+
build/test evidence
```

It should prefer the smallest appropriate migration.

Preferred:

```text
2 files
4 lines
```

over:

```text
15 files
120 lines
```

when both would solve the same problem.

The project should optimize for:

- targeted changes
- minimal unrelated modifications
- understandable patches
- preservation of existing project behavior

---

# 15. Phase 7 — Repair

The repair system may use Codex or another capable coding model.

The model should receive:

- the structured evidence bundle
- causal hypothesis
- migration plan
- relevant files
- relevant build/test feedback
- constraints on allowed changes

The model should modify the repair workspace.

However:

> **The model is not allowed to decide whether its own repair is correct.**

Its job is to propose and implement a candidate migration.

Execution decides success.

---

# 16. Phase 8 — Execution Loop

After each repair attempt, BumpShield must execute the real project.

At minimum:

```bash
mvn compile
mvn test
```

or the repository's equivalent Maven commands when necessary.

If execution fails:

```text
repair
↓
build/test
↓
FAIL
```

the new failure becomes additional evidence.

The loop becomes:

```text
hypothesis
↓
candidate migration
↓
experiment
↓
observation
↓
updated evidence
↓
revised hypothesis or repair
```

The prototype should use a bounded repair budget.

Recommended MVP:

```text
MAX_REPAIR_ATTEMPTS = 3
```

The system should never retry forever.

---

# 17. Phase 9 — Independent Verification

Verification must be deterministic whenever possible.

A repair may only receive:

```text
VERIFIED MIGRATION
```

when objective checks pass.

At minimum verify:

```text
requested dependency still uses requested upgraded version
AND
project compiles
AND
required tests pass
```

Also check for obvious cheating or invalid repair behavior.

Examples:

```text
dependency downgraded
dependency removed
tests deleted
tests disabled
test execution skipped
application code commented out merely to avoid the failure
unrelated destructive modifications
```

Suspicious cases may return:

```text
NEEDS HUMAN REVIEW
```

rather than a verified result.

---

# 18. Fundamental Verification Rule

> **No green claim without green execution.**

These are not equivalent:

```text
LLM:
"The repair should work."
```

and:

```text
Maven:
BUILD SUCCESS
Tests:
PASS
Verifier:
target dependency retained
```

Only the second can produce:

```text
VERIFIED MIGRATION
```

---

# 19. Anti-Cheating Rule

Suppose the requested migration is:

```text
foo 2.0 → 3.0
```

The following is **not** a repair:

```text
foo 3.0 → 2.0
```

even if the project builds afterward.

The target dependency must remain at the requested upgraded version.

A successful repair requires:

```text
requested dependency retained ✅
build succeeds ✅
tests succeed ✅
```

---

# 20. Required Output

BumpShield should produce a structured migration report.

Example:

```text
BumpShield Migration Report
===========================

TARGET DEPENDENCY

foo-core
2.8.0 → 3.0.0


REGRESSION

Base revision:
PASS

Updated revision:
FAIL


FAILURE

FooParser.java:84

Missing:
parseValue(String)


DEPENDENCY CHANGES

foo-core
2.8.0 → 3.0.0
DIRECT

foo-parser
4.6.0 → 5.0.0
TRANSITIVE


ROOT CAUSE

foo-core 3.0 causes foo-parser to resolve to 5.0.

foo-parser 5.0 removed parseValue(String).

FooParser.java:84 still calls the removed method.


REPAIR

Modified:
FooParser.java

Lines changed:
2


VERIFICATION

Target dependency retained:
PASS

Compilation:
PASS

Tests:
438 / 438 PASS

Repair attempts:
1


FINAL STATUS

VERIFIED MIGRATION
```

---

# 21. Final Status Values

The MVP should use a small explicit set of outcomes.

Recommended:

```text
VERIFIED_MIGRATION
```

```text
UNRESOLVED
```

```text
NEEDS_HUMAN_REVIEW
```

Optionally:

```text
INVALID_CASE
```

for benchmark or task inputs that fail the base assumptions.

---

# 22. Primary Success Metric

## Verified Repair Rate

```text
       number of verified migrations
VRR = --------------------------------
       total attempted valid cases
```

A case counts as successful only when:

```text
requested upgraded dependency retained
+
build succeeds
+
tests succeed
+
verification checks pass
```

The purpose of BumpShield is not merely to produce plausible patches.

The purpose is to increase **verified** dependency migrations.

---

# 23. Secondary Metrics

The system should record enough information to eventually measure:

## Root Cause Localization Accuracy

Did BumpShield identify the correct dependency/API/configuration cause?

## Repair Attempts

How many repair experiments were required?

## Time to Verified Repair

How long did the entire workflow take?

## LLM/API Cost

How much model usage was required?

## Patch Size

Track:

```text
files modified
lines added
lines removed
```

## Direct vs Transitive Performance

Compare success on:

```text
direct dependency breakages
```

versus:

```text
transitive dependency breakages
```

---

# 24. Baseline for Research Comparison

The future baseline should be intentionally simple.

Give a strong coding model:

```text
repository
+
dependency upgrade
+
compiler/test failure
```

and ask it to:

```text
analyze the problem
and generate a repair
```

with one repair attempt.

Then independently execute:

```text
build
tests
```

Compare its Verified Repair Rate with BumpShield.

The key research comparison is:

```text
error → immediate patch
```

versus:

```text
error
→ dependency analysis
→ evidence
→ causal hypothesis
→ targeted repair
→ execution
→ verification
```

---

# 25. MVP Architecture Principle

The first version should **not** be implemented as many autonomous LLM agents.

Use deterministic software for deterministic tasks.

Recommended architecture:

```text
Task
 │
 ▼
Repository Workspace
 │
 ▼
Failure Reproducer
 │
 ▼
Dependency Diff
 │
 ▼
Failure Parser / Localizer
 │
 ▼
API Evidence Collector
 │
 ▼
Investigator      ← AI
 │
 ▼
Repair Engine     ← AI
 │
 ▼
Maven Executor
 │
 ├── FAIL → evidence → retry
 │
 ▼
Independent Verifier
 │
 ▼
Migration Report
```

Only components that genuinely require reasoning should depend on an LLM.

For the two-day MVP, the primary AI components are:

```text
Investigator
Repair Engine
```

The following should remain deterministic:

```text
Git operations
command execution
Maven invocation
dependency parsing
dependency diffing
build-log parsing where possible
workspace management
version verification
test verification
anti-cheating checks
report metadata
```

---

# 26. Two-Day Build Target

The two-day prototype should aim to support:

```text
Java/Maven only

Input:
repository
+ base commit
+ broken commit
+ target dependency update

Capabilities:

✓ isolated repository workspaces

✓ base-vs-updated regression reproduction

✓ Maven dependency-tree collection

✓ before/after dependency diff

✓ direct and transitive version-change detection

✓ compiler/test failure localization

✓ source-context extraction

✓ basic Java API evidence

✓ explicit causal hypothesis

✓ Codex-powered migration

✓ maximum three repair attempts

✓ real Maven compile/test execution

✓ dependency-version verification

✓ basic anti-cheating checks

✓ structured migration report
```

---

# 27. Demo Target

A convincing demo should contain at least three examples.

## Case A — Direct API Removal

```text
Dependency A upgraded
↓
API method removed
↓
project fails
```

## Case B — Signature Change

```text
parse(x)
```

becomes:

```text
parse(x, options)
```

## Case C — Transitive Breakage

```text
User upgrades A
↓
A changes B
↓
B changes C
↓
C changes or removes API
↓
project breaks
```

Case C is especially important because it demonstrates the value of dependency-level causal reasoning.

---

# 28. Non-Goals for the Two-Day MVP

The initial prototype must **not** expand into a generic autonomous software engineer.

Do not prioritize:

```text
Python dependency support

npm support

Rust/Cargo support

Gradle support

generic bug fixing

generic pull-request repair

generic code review

vector databases

large RAG infrastructure

Neo4j

complex graph databases

LangGraph orchestration

many independent LLM agents

large web dashboard

semantic-equivalence verification

automatic regression-test generation

property-based testing

full behavioral differential testing

automatic online research

support for every Maven edge case
```

These may become future extensions.

They are not required to prove the core idea.

---

# 29. What BumpShield Is NOT

BumpShield is not:

> a generic coding assistant.

BumpShield is not:

> an autonomous software engineer.

BumpShield is not:

> a dependency updater.

BumpShield is not:

> an LLM wrapper around compiler errors.

BumpShield is specifically:

> **a causal investigation and verified migration system for failures introduced by dependency upgrades.**

---

# 30. Engineering Principles

All implementation work should follow these principles.

## 30.1 Deterministic where possible

Do not use an LLM to perform work that can be reliably implemented with normal code.

## 30.2 Structured data between components

Components should communicate using typed models rather than unstructured dictionaries or natural-language blobs.

Examples:

```text
TaskSpec
CommandResult
ExecutionResult
DependencyNode
DependencyChange
DependencyDiff
FailureSignal
EvidenceBundle
RootCauseHypothesis
RepairAttempt
VerificationResult
MigrationReport
```

## 30.3 Preserve evidence

Each run should store its artifacts.

Suggested structure:

```text
.bumpshield/
└── runs/
    └── <run-id>/
        ├── task.json
        ├── base-build.log
        ├── updated-build.log
        ├── dependencies-before.json
        ├── dependencies-after.json
        ├── dependency-diff.json
        ├── failures.json
        ├── evidence.json
        ├── hypothesis.json
        ├── attempts/
        │   ├── 1/
        │   │   ├── patch.diff
        │   │   ├── build.log
        │   │   └── result.json
        │   └── ...
        ├── verification.json
        └── report.json
```

## 30.4 Never hide failures

Do not silently swallow:

- subprocess failures
- Maven failures
- Git failures
- parser failures
- LLM failures
- timeouts

All failures must become structured information.

## 30.5 Bound execution

Every external command must have a timeout.

Every repair loop must have a maximum number of attempts.

## 30.6 Keep patches minimal

Prefer targeted migrations over broad refactors.

## 30.7 Separate proposal from verification

The system that proposes a patch must not be the authority that declares the patch successful.

---

# 31. Suggested Project Structure

```text
bumpshield/
│
├── cli.py
├── models.py
├── config.py
│
├── repo/
│   ├── git.py
│   └── workspace.py
│
├── analysis/
│   ├── reproducer.py
│   ├── dependency_diff.py
│   ├── failure_parser.py
│   ├── source_locator.py
│   └── api_diff.py
│
├── agent/
│   ├── investigator.py
│   ├── repairer.py
│   └── prompts.py
│
├── execution/
│   ├── command_runner.py
│   ├── maven.py
│   └── verifier.py
│
├── report/
│   └── generator.py
│
└── tests/
```

This structure may evolve if there is a strong engineering reason.

Do not change it merely to add unnecessary abstractions.

---

# 32. Core Domain Models

The implementation should converge around typed domain models.

Example conceptual models:

```python
TaskSpec
```

Represents the dependency migration task.

```python
CommandResult
```

Represents one external process execution.

```python
ExecutionResult
```

Represents Maven build/test execution.

```python
DependencyNode
```

Represents one resolved dependency.

```python
DependencyChange
```

Represents added, removed, or updated dependency information.

```python
DependencyDiff
```

Represents the complete before/after dependency comparison.

```python
FailureSignal
```

Represents a localized compiler or test failure.

```python
EvidenceBundle
```

Contains the evidence the investigator needs.

```python
RootCauseHypothesis
```

Contains the suspected cause and its supporting causal chain.

```python
RepairAttempt
```

Contains patch metadata and resulting execution feedback.

```python
VerificationResult
```

Contains deterministic final checks.

```python
MigrationReport
```

Contains the final user-facing result.

---

# 33. Example Evidence Bundle

A typical evidence object may look like:

```json
{
  "target_update": {
    "dependency": "org.example:foo-core",
    "old_version": "2.8.0",
    "new_version": "3.0.0"
  },

  "regression": {
    "base": "PASS",
    "updated": "FAIL"
  },

  "dependency_changes": [
    {
      "dependency": "org.example:foo-parser",
      "old_version": "4.6.0",
      "new_version": "5.0.0",
      "relationship": "TRANSITIVE"
    }
  ],

  "failures": [
    {
      "category": "missing_method",
      "file": "src/main/java/example/FooParser.java",
      "line": 84,
      "symbol": "parseValue"
    }
  ],

  "api_evidence": {
    "old_api": "parseValue(String)",
    "new_api": "parse(String, ParserOptions)"
  }
}
```

This structured object should be the main interface between deterministic analysis and the LLM investigator.

---

# 34. Codex Responsibilities

When Codex is used to develop BumpShield itself, it should:

1. read this file first
2. inspect the existing repository before modifying it
3. implement only the requested phase
4. preserve existing architecture unless a change is justified
5. use typed interfaces
6. add tests for deterministic logic
7. run relevant tests before finishing
8. report exactly what changed
9. avoid implementing future phases early
10. avoid introducing unnecessary dependencies

When Codex is used **inside BumpShield as the repair model**, it should:

1. inspect the supplied evidence
2. state or consume the causal hypothesis
3. modify only relevant project files where possible
4. preserve the target upgraded dependency
5. avoid disabling tests
6. avoid downgrading dependencies
7. avoid unrelated refactors
8. produce a candidate migration
9. allow BumpShield to independently execute and verify it

---

# 35. Definition of MVP Success

The MVP is successful when the following complete flow works on real Java/Maven dependency-breakage examples:

```text
working revision passes
↓
upgraded revision fails
↓
BumpShield detects dependency changes
↓
BumpShield localizes the failure
↓
BumpShield gathers relevant API evidence
↓
BumpShield states a concrete causal hypothesis
↓
BumpShield produces a targeted migration
↓
Maven compile/tests execute successfully
↓
BumpShield confirms target dependency remains upgraded
↓
BumpShield emits VERIFIED_MIGRATION
```

The most important demonstration is not the text explanation.

It is:

```text
OLD PROJECT      PASS
UPGRADED PROJECT FAIL
REPAIRED PROJECT PASS
UPGRADED VERSION RETAINED
```

with evidence explaining **why**.

---

# 36. Definition of Research Success

Longer term, BumpShield succeeds scientifically if:

> **On a fixed set of previously unseen breaking dependency upgrades, BumpShield achieves a meaningfully higher Verified Repair Rate than a strong one-shot LLM baseline, and ablation experiments show that at least one causal-analysis component contributes measurable improvement.**

The system should eventually make it possible to ask:

```text
Does build feedback help?

Does API diff help?

Does dependency graph reasoning help?

Does upstream evidence help?

Does explicitly stating a causal hypothesis help?

Does verification prevent false success?
```

The goal is not merely:

```text
BumpShield > baseline
```

The deeper goal is:

```text
WHY does BumpShield > baseline?
```

---

# 37. Final Mental Model

Whenever there is uncertainty about what BumpShield should do, return to these six questions:

```text
A dependency was upgraded and the project broke.

BumpShield must determine:

1. What changed?

2. What actually caused the failure?

3. Why did that change break this project?

4. What project code must change?

5. What is the smallest appropriate migration?

6. Can real execution prove that the migration works?
```

If a feature does not materially help answer one of these questions or improve the reliability of the answer, it is probably not required for the MVP.

---

# 38. Final Project Principle

> **The compiler tells us where the software broke. BumpShield tries to determine why it broke, repair the actual cause, and prove the migration through execution.**

And the final rule remains:

> **No green claim without green execution.**
