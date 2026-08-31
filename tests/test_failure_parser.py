from pathlib import Path

import pytest

from bumpshield.analysis.failure_parser import FailureParser
from bumpshield.models import (
    CommandResult,
    ExecutionResult,
    ExecutionStatus,
    FailureCategory,
)


def test_missing_method_extracts_position_symbol_location_and_raw_evidence() -> None:
    text = """\
[INFO] Compiling 1 source file
[ERROR] /tmp/work/src/main/java/example/Foo.java:[84,21] cannot find symbol
[ERROR]   symbol:   method parseValue(java.lang.String)
[ERROR]   location: variable parser of type example.Parser
"""

    failure = FailureParser().parse_text(text)[0]

    assert failure.category is FailureCategory.MISSING_SYMBOL
    assert failure.reported_file == "/tmp/work/src/main/java/example/Foo.java"
    assert failure.line == 84
    assert failure.column == 21
    assert failure.symbol == "parseValue(java.lang.String)"
    assert failure.location == "variable parser of type example.Parser"
    assert failure.message == "cannot find symbol"
    assert "symbol:" in (failure.raw_excerpt or "")


@pytest.mark.parametrize(
    ("symbol_line", "expected"),
    [
        ("class LegacyParser", "LegacyParser"),
        ("variable DEFAULT_MODE", "DEFAULT_MODE"),
    ],
)
def test_missing_class_and_variable_are_structured(
    symbol_line: str,
    expected: str,
) -> None:
    text = (
        "[ERROR] src/main/java/example/Foo.java:[4,8] cannot find symbol\n"
        f"[ERROR] symbol: {symbol_line}\n"
    )

    failure = FailureParser().parse_text(text)[0]

    assert failure.category is FailureCategory.MISSING_SYMBOL
    assert failure.symbol == expected


def test_method_argument_mismatch_retains_required_and_found_text() -> None:
    text = """\
[ERROR] src/main/java/example/Foo.java:[12,9] method parse in class Parser cannot be applied to given types;
[ERROR]   required:
[ERROR]   java.lang.String,ParserOptions
[ERROR]   found:
[ERROR]   java.lang.String
[ERROR]   reason: actual and formal argument lists differ in length
"""

    failure = FailureParser().parse_text(text)[0]

    assert failure.category is FailureCategory.METHOD_ARGUMENT_MISMATCH
    assert failure.symbol == "parse"
    assert failure.required == "java.lang.String,ParserOptions"
    assert failure.found == "java.lang.String"


def test_package_not_found_extracts_package_symbol() -> None:
    failure = FailureParser().parse_text(
        "[ERROR] src/main/java/example/Foo.java:[3,25] "
        "package org.example.legacy does not exist\n"
    )[0]

    assert failure.category is FailureCategory.PACKAGE_NOT_FOUND
    assert failure.symbol == "org.example.legacy"
    assert failure.line == 3


def test_incompatible_types_retains_conversion_text() -> None:
    text = """\
[ERROR] src/main/java/example/Foo.java:[18,12] incompatible types:
[ERROR] java.lang.String cannot be converted to example.Result
"""

    failure = FailureParser().parse_text(text)[0]

    assert failure.category is FailureCategory.INCOMPATIBLE_TYPES
    assert "String cannot be converted to example.Result" in failure.message


def test_source_positioned_unknown_compiler_error_is_preserved() -> None:
    failure = FailureParser().parse_text(
        "[ERROR] src/main/java/example/Foo.java:[7,5] illegal start of expression\n"
    )[0]

    assert failure.category is FailureCategory.COMPILATION_ERROR_OTHER
    assert failure.message == "illegal start of expression"


def test_assertion_failure_retains_test_identity_and_project_frames() -> None:
    text = """\
[ERROR] com.example.FooTest.testParsing -- Time elapsed: 0.01 s <<< FAILURE!
[ERROR] java.lang.AssertionError: expected:<1> but was:<2>
[ERROR] at java.base/java.util.List.get(List.java:1)
[ERROR] at org.junit.jupiter.api.Assertions.fail(Assertions.java:55)
[ERROR] at com.example.Parser.parse(Parser.java:51)
[ERROR] at com.example.FooTest.testParsing(FooTest.java:27)
[INFO] Results:
"""

    failure = FailureParser().parse_text(text)[0]

    assert failure.category is FailureCategory.ASSERTION_FAILURE
    assert failure.test_class == "com.example.FooTest"
    assert failure.test_method == "testParsing"
    assert failure.exception_type == "java.lang.AssertionError"
    assert failure.message == "expected:<1> but was:<2>"
    assert [frame.file_name for frame in failure.stack_frames] == [
        "Parser.java",
        "FooTest.java",
    ]


def test_test_exception_is_distinct_from_assertion_failure() -> None:
    text = """\
[ERROR] loads(com.example.FooTest) Time elapsed: 0.01 s <<< ERROR!
[ERROR] java.lang.IllegalStateException: broken state
[ERROR] at com.example.FooTest.loads(FooTest.java:33)
"""

    failure = FailureParser().parse_text(text)[0]

    assert failure.category is FailureCategory.TEST_EXCEPTION
    assert failure.exception_type == "java.lang.IllegalStateException"
    assert failure.line == 33


def test_surefire_summary_without_details_becomes_generic_test_failure() -> None:
    failure = FailureParser().parse_text(
        "[ERROR] Tests run: 4, Failures: 1, Errors: 0, Skipped: 0\n"
    )[0]

    assert failure.category is FailureCategory.TEST_FAILURE
    assert failure.file is None
    assert failure.line is None


def test_repeated_compiler_diagnostic_is_deduplicated() -> None:
    diagnostic = (
        "[ERROR] src/main/java/example/Foo.java:[9,3] cannot find symbol\n"
        "[ERROR] symbol: method gone()\n"
    )

    failures = FailureParser().parse_text(diagnostic + diagnostic)

    assert len(failures) == 1


def test_distinct_failures_keep_first_appearance_order() -> None:
    text = """\
[ERROR] src/main/java/example/Foo.java:[10,3] cannot find symbol
[ERROR] symbol: method first()
[ERROR] src/main/java/example/Bar.java:[20,5] incompatible types: X cannot be converted to Y
"""

    failures = FailureParser().parse_text(text)

    assert [failure.reported_file for failure in failures] == [
        "src/main/java/example/Foo.java",
        "src/main/java/example/Bar.java",
    ]


def test_execution_parser_consumes_stdout_and_stderr_and_deduplicates() -> None:
    diagnostic = (
        "[ERROR] src/main/java/example/Foo.java:[9,3] cannot find symbol\n"
        "[ERROR] symbol: method gone()\n"
    )
    command = CommandResult(
        command=("mvn", "-B", "test"),
        cwd=Path("/tmp/work"),
        exit_code=1,
        stdout=diagnostic,
        stderr=diagnostic,
        duration_seconds=1.0,
    )

    failures = FailureParser().parse(
        ExecutionResult(status=ExecutionStatus.FAIL, commands=(command,))
    )

    assert len(failures) == 1
