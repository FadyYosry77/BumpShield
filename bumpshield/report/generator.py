"""Deterministic final migration report rendering."""

from __future__ import annotations

from bumpshield.models import MigrationReport


def render_migration_report(report: MigrationReport) -> str:
    """Render objective repair and verification facts without provider claims."""
    target = report.task.target_dependency
    lines = [
        "BumpShield Migration Report",
        "===========================",
        "",
        "Target Dependency",
        f"{target.group_id}:{target.artifact_id}",
        f"{target.old_version} -> {target.new_version}",
    ]
    if report.diagnosis_summary:
        lines.extend(["", "Diagnosis", report.diagnosis_summary])
    if report.plan_summary:
        lines.extend(["", "Migration Plan", report.plan_summary])
    lines.extend(["", f"Repair attempts: {len(report.attempts)}"])
    if report.winning_attempt is not None:
        lines.append(f"Winning attempt: {report.winning_attempt}")
    for attempt in report.attempts:
        lines.extend(
            [
                "",
                f"Attempt {attempt.attempt_number}: {attempt.status.value}",
                f"Files changed: {len(attempt.modified_files)}",
                f"Lines: +{attempt.lines_added} -{attempt.lines_removed}",
                "Compile: "
                + (
                    attempt.compile_result.status.value
                    if attempt.compile_result is not None
                    else "NOT_RUN"
                ),
                "Tests: "
                + (
                    attempt.test_result.status.value
                    if attempt.test_result is not None
                    else "NOT_RUN"
                ),
            ]
        )
    if report.verification is not None:
        lines.extend(["", "Independent Verification"])
        lines.extend(
            f"{check.name}: {check.status.value} - {check.details}"
            for check in report.verification.checks
        )
    lines.extend(
        [
            "",
            "Final Status",
            report.status.value,
            "",
            f"Duration seconds: {report.duration_seconds:.3f}",
        ]
    )
    return "\n".join(lines) + "\n"
