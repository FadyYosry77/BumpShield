# BoneCP Real-World Showcase

## Upstream Project

BoneCP is a genuine public Java/Maven project from
`https://github.com/wwadge/bonecp.git`. This showcase uses upstream commit
`2ea6baad5c5e0751856c00dd7633b1b767249ea2` (tag
`bonecp-parent-0.8.0.RELEASE`) under Apache License 2.0.

## Constructed Dependency Upgrade

The showcase reproducibility branch adapts the legacy build to the BoneCP core
module under a pinned Java 8/Maven 3.2.5 toolchain, then changes only Guava
`15.0` to `21.0`. This is a constructed upgrade, not an upstream historical
regression. It is separate from `BUMP-FINAL-v1` and is excluded from all frozen
20-case statistics.

## Regression

The base revision passes the Maven build with 197 tests, zero failures, zero
errors, and three pre-existing skips. The upgraded revision fails compilation
at two production call sites that invoke `Objects.toStringHelper(...)`.

## What BumpShield Found

BumpShield confirmed the direct Guava transition, localized both Java
failures, attributed `com.google.common.base.Objects` to Guava, and produced a
`SUPPORTED_DIAGNOSIS` with deterministic evidence score 100/100. Planning
returned `PLAN_READY` with a two-file source boundary.

## API Evidence

Old/new JAR inspection classified the change as `REMOVED_MEMBER`:
`Objects.toStringHelper(java.lang.Object)` is present in Guava 15 and absent in
Guava 21 while the containing class remains present.

## Migration

On one fresh provider-backed attempt, Codex changed only the two allowed files,
replacing the `Objects` import and calls with `MoreObjects`. The Git-ground-
truth patch contains two files and four additions/four deletions. An earlier
run was unresolved because Codex quota expired after producing a patch; that
run was not manually accepted.

## Independent Verification

The existing BumpShield verifier retained Guava 21.0, compiled the source, ran
the same 197-test suite successfully, found no deleted or newly disabled tests,
found no new test skipping, and accepted patch scope and safety. Final status:
`VERIFIED_MIGRATION`.

## Limitations

This is one real project with a benchmark-constructed upgrade and a legacy
build adaptation. It demonstrates end-to-end applicability; it is not a new
benchmark or evidence of general success rates. The three skips existed in
both base and repaired runs, and two known flaky legacy test classes are
excluded identically from both showcase revisions.

## Reproduction

Portable evidence and exact commits are recorded in
[`showcase/real-world`](../showcase/real-world/README.md). The committed replay
is offline and makes no Maven, Java, Codex, Git, or network calls. Rebuilding
the external working repository requires the recorded upstream commit, the
documented build adaptations, Java 8, Maven 3.2.5, and a local dependency
cache; no cloned repository or cache is committed here.

