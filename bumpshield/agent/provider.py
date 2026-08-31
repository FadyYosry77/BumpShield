"""Bounded repair-provider interface and locally observed Codex CLI adapter."""

from __future__ import annotations

import shutil
from typing import Protocol

from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandExecutionError, CommandRunner
from bumpshield.models import (
    RepairContext,
    RepairFeedback,
    RepairProviderResult,
    RepairProviderStatus,
    RepairRequest,
)
from bumpshield.repo.workspace import RepositoryWorkspace

MAX_REPAIR_INSTRUCTION_CHARS = 40_000
MAX_FEEDBACK_EXCERPT_CHARS = 4_000


class RepairProvider(Protocol):
    """One narrow source-editing boundary."""

    def repair(
        self,
        workspace: RepositoryWorkspace,
        request: RepairRequest,
    ) -> RepairProviderResult:
        """Modify only repair workspace and return non-authoritative output."""
        ...


class CodexRepairProvider:
    """Run locally installed Codex non-interactively inside repair worktree."""

    name = "codex-cli"

    def __init__(
        self,
        runner: CommandRunner | None = None,
        config: BumpShieldConfig | None = None,
    ) -> None:
        self.runner = runner or CommandRunner()
        self.config = config or BumpShieldConfig()

    def repair(
        self,
        workspace: RepositoryWorkspace,
        request: RepairRequest,
    ) -> RepairProviderResult:
        """Use observed ``codex exec`` contract with bounded execution."""
        executable = self.config.repair_provider_executable
        if shutil.which(executable) is None:
            return RepairProviderResult(
                status=RepairProviderStatus.UNAVAILABLE,
                provider=self.name,
                summary=f"repair provider unavailable: {executable} executable not found",
                raw_output="",
                duration_seconds=0.0,
            )
        command = (
            executable,
            "--sandbox",
            "workspace-write",
            "--ask-for-approval",
            "never",
            "--cd",
            str(workspace.path.resolve()),
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--disable",
            "skill_search",
            "--ephemeral",
            "--color",
            "never",
            request.instruction,
        )
        try:
            result = self.runner.run(
                command,
                cwd=workspace.path,
                timeout=self.config.repair_provider_timeout_seconds,
            )
        except CommandExecutionError as error:
            return RepairProviderResult(
                status=RepairProviderStatus.ERROR,
                provider=self.name,
                summary=str(error),
                raw_output="",
                duration_seconds=0.0,
            )
        raw_output = _provider_output(result.stdout, result.stderr)
        if result.timed_out:
            status = RepairProviderStatus.TIMEOUT
            summary = "Codex repair provider timed out"
        elif result.exit_code != 0:
            status = RepairProviderStatus.ERROR
            summary = f"Codex repair provider exited {result.exit_code}"
        else:
            status = RepairProviderStatus.SUCCESS
            summary = "Codex repair provider completed; Git will inspect actual changes"
        return RepairProviderResult(
            status=status,
            provider=self.name,
            summary=summary,
            raw_output=raw_output,
            duration_seconds=result.duration_seconds,
        )


def build_repair_request(
    context: RepairContext,
    attempt_number: int,
    feedback: RepairFeedback | None,
) -> RepairRequest:
    """Build focused instruction while keeping constraints and evidence bounded."""
    plan = context.plan
    target = plan.target_upgrade
    required = [
        "You are editing an isolated BumpShield repair worktree.",
        "Do not modify files outside this workspace.",
        "Limit reads to workspace and local build/toolchain inputs needed for migration.",
        "Do not modify BumpShield state or Git history. Do not commit.",
        "Produce smallest correct Java/Maven dependency migration.",
        "Do not claim success; BumpShield independently verifies Git, Maven, and dependencies.",
        "",
        f"Attempt: {attempt_number}",
        f"Diagnosis: {context.diagnosis_summary}",
        f"Migration: {plan.migration_kind.value}",
        f"Required outcome: {plan.required_outcome}",
        (
            "Target dependency must remain upgraded: "
            f"{target.group_id}:{target.artifact_id}:{target.new_version}"
        ),
    ]
    if plan.affected_dependency is not None:
        causal = plan.affected_dependency.after or plan.affected_dependency.before
        if causal is not None:
            required.append(
                "Causal dependency resolution must not be downgraded: "
                f"{causal.group_id}:{causal.artifact_id}:{causal.version}"
            )
    if plan.affected_class:
        required.append(f"Affected class: {plan.affected_class}")
    if plan.affected_member:
        required.append(f"Affected member: {plan.affected_member}")
    required.extend(
        [
            "",
            "Initial allowed files:",
            *(f"- {path}" for path in plan.allowed_files),
            "Additional files require evidence-backed justification.",
            "",
            "Mandatory constraints:",
            *(f"- {constraint.value}" for constraint in plan.constraints),
            "- Do not downgrade or remove target dependency.",
            "- Do not delete, disable, weaken, or skip tests.",
            "- Do not suppress compiler errors or remove functionality merely to compile.",
            "- Avoid unrelated refactors.",
        ]
    )
    if plan.new_api_candidates:
        required.extend(
            [
                "",
                "Observed new API candidates (not verified replacements):",
                *(
                    f"- {candidate.member.declaration}"
                    for candidate in plan.new_api_candidates
                ),
                (
                    "These declarations are migration evidence only. Semantic equivalence "
                    "has not been proven."
                ),
            ]
        )
    if plan.missing_parameter_types:
        required.extend(
            [
                "",
                "Observed new required parameter types:",
                *(f"- {value}" for value in plan.missing_parameter_types),
                "No argument value was selected by deterministic planning.",
            ]
        )

    feedback_lines: list[str] = []
    if feedback is not None:
        feedback_lines.extend(
            [
                "",
                "Previous attempt feedback:",
                feedback.summary,
                f"Previous status: {feedback.attempt_status.value}",
                "Previous changed files: "
                + ", ".join(map(str, feedback.changed_files)),
            ]
        )
        if feedback.primary_failure is not None:
            failure = feedback.primary_failure
            feedback_lines.append(
                "Representative failure: "
                f"{failure.category.value}: {failure.message}"
            )
        if feedback.bounded_excerpt:
            feedback_lines.extend(
                [
                    "Bounded execution excerpt:",
                    feedback.bounded_excerpt[-MAX_FEEDBACK_EXCERPT_CHARS:],
                ]
            )
        feedback_lines.extend(f"Safety issue: {issue}" for issue in feedback.safety_issues)

    source_lines = ["", "Bounded source context:"]
    for source in context.source_contexts:
        source_lines.append(
            f"--- {source.file}:{source.start_line}-{source.end_line} "
            f"(focus {source.focus_line})"
        )
        source_lines.extend(f"{line.number}: {line.text}" for line in source.lines)

    fixed = "\n".join(required + feedback_lines) + "\n"
    remaining = max(0, MAX_REPAIR_INSTRUCTION_CHARS - len(fixed))
    source = "\n".join(source_lines)
    instruction = fixed + source[:remaining]
    return RepairRequest(attempt_number, instruction, context, feedback)


def _provider_output(stdout: str, stderr: str) -> str:
    return f"[stdout]\n{stdout}\n[stderr]\n{stderr}"
