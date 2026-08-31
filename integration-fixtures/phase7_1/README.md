# Phase 7.1 transitive migration fixture

This fixture exercises a real transitive Java/Maven API break:

```text
application
└── core-lib 1.0.0 -> 2.0.0
    └── parser-lib 1.0.0 -> 2.0.0
```

`parser-lib` 1.0.0 exposes `Parser.parseValue(String)`. Version 2.0.0
replaces it with `Parser.parse(String, ParserOptions)`. Application source keeps
calling the removed method, so changing only `core-lib` from 1.0.0 to 2.0.0
causes a real compiler failure. JUnit tests require whitespace-trimming behavior;
removing the call or returning a constant cannot satisfy them.

Library directories are installed into a disposable real Maven repository for
the integration run. `application/pom.xml` is the base revision. During setup,
`application/pom.updated.xml` replaces it in the updated Git revision; source
and tests remain unchanged.

Normal unit tests do not execute this fixture and require no Java, Maven,
Codex, or network access.

For a copyable walkthrough that prepares this fixture, reproduces the failure,
runs BumpShield, and inspects the verified patch, see
[`docs/demo.md`](../../docs/demo.md).
