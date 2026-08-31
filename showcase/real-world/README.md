# BoneCP real-world showcase

This is a compact evidence snapshot from a genuine open-source Java/Maven
project. BoneCP source comes from the public upstream repository at commit
`2ea6baad5c5e0751856c00dd7633b1b767249ea2` under Apache License 2.0.

The dependency regression is a **constructed dependency upgrade**: the
showcase changes Guava `15.0` to `21.0`; it is not claimed as an upstream
historical BoneCP regression. The reproducibility branch narrows the legacy
reactor to the core module, routes `mvnw` to that module, pins the compatible
Surefire version, suppresses legacy compiler-warning noise, and excludes two
known flaky legacy tests. Both revisions use the same adaptations. The base
build runs 197 tests successfully with three pre-existing skips.

The upgrade makes two production call sites fail because
`Objects.toStringHelper(...)` is absent from Guava 21. BumpShield attributed
the API to Guava, produced a `SUPPORTED_DIAGNOSIS` with deterministic evidence
score 100/100, bounded repair to two files, and independently verified a
four-line migration to `MoreObjects.toStringHelper(...)`.

Final status: `VERIFIED_MIGRATION`. This showcase is separate from
`BUMP-FINAL-v1` and must not be included in its 20-case benchmark statistics.
The snapshot contains no clone, Maven cache, target directory, or raw provider
log.

