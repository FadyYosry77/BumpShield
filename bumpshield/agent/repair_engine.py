"""Constrained repair attempts with deterministic execution and verification."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from bumpshield.agent.provider import (
    CodexRepairProvider,
    RepairProvider,
    build_repair_request,
)
from bumpshield.agent.repairer import MigrationPlanningService, PlanningError
from bumpshield.analysis.failure_parser import FailureParser
from bumpshield.analysis.patch_analysis import PatchAnalysisError, PatchAnalyzer
from bumpshield.analysis.source_locator import SourceLocator
from bumpshield.config import BumpShieldConfig
from bumpshield.execution.command_runner import CommandRunner
from bumpshield.execution.maven import MavenExecutor
from bumpshield.execution.verifier import (
    DependencyValidator,
    IndependentVerifier,
    RepairMavenExecution,
)
from bumpshield.models import (
    DependencyValidationResult,
    ExecutionResult,
    ExecutionStatus,
    MigrationPlanningResult,
    MigrationReport,
    MigrationStatus,
    PatchAnalysis,
    PlanStatus,
    RepairAttempt,
    RepairAttemptStatus,
    RepairFeedback,
    RepairProviderResult,
    RepairProviderStatus,
    RepairResult,
    TaskSpec,
    VerificationResult,
    VerificationStatus,
    WorkspaceKind,
)
from bumpshield.repo.workspace import RepositoryWorkspace, WorkspaceError, WorkspaceManager
from bumpshield.report.generator import render_migration_report
from bumpshield.run import (
    RunSetupError,
    execution_log_text,
    require_external_path,
    validate_task_repository,
)

LOGGER = logging.getLogger(__name__)
MAX_FEEDBACK_LOG_CHARS = 4_000


class RepairError(RuntimeError):
    """Raised when repair infrastructure cannot produce trustworthy evidence."""


class RepairPlanning(Protocol):
    """Phase 6 boundary consumed by repair orchestration."""

    def plan(self, task: TaskSpec, run_id: str | None = None) -> MigrationPlanningResult:
        """Return the bounded Phase 6 context for this task."""
        ...


class RepairEngine:
    """Run bounded fresh repair attempts and independently verify candidates."""

    def __init__(
        self,
        planning: RepairPlanning | None = None,
        provider: RepairProvider | None = None,
        maven: RepairMavenExecution | None = None,
        patch_analyzer: PatchAnalyzer | None = None,
        dependency_validator: DependencyValidator | None = None,
        verifier: IndependentVerifier | None = None,
        runner: CommandRunner | None = None,
        config: BumpShieldConfig | None = None,
    ) -> None:
        self.config = config or BumpShieldConfig()
        self.runner = runner or CommandRunner()
        self.planning = planning or MigrationPlanningService(
            runner=self.runner, config=self.config
        )
        self.provider = provider or CodexRepairProvider(
            runner=self.runner, config=self.config
        )
        self.maven = maven or MavenExecutor(runner=self.runner)
        self.patch_analyzer = patch_analyzer or PatchAnalyzer()
        self.dependency_validator = dependency_validator or DependencyValidator(
            self.maven
        )
        self.verifier = verifier or IndependentVerifier()
        self.failure_parser = FailureParser()
        self.source_locator = SourceLocator(context_radius=8)

    def repair(self, task: TaskSpec) -> RepairResult:
        """Repair only an isolated updated-revision worktree, never source repo."""
        started = time.monotonic()
        try:
            planning = self.planning.plan(task)
        except PlanningError as error:
            raise RepairError(str(error)) from error
        run_directory = planning.plan.artifact_directory.resolve()
        try:
            require_external_path(run_directory, task.repository.resolve())
            repository, _ = validate_task_repository(task, self.runner)
        except RunSetupError as error:
            raise RepairError(str(error)) from error
        artifacts = RepairArtifacts(run_directory)

        if planning.plan.status is not PlanStatus.PLAN_READY:
            result = self._finish(
                planning,
                (),
                MigrationStatus.NEEDS_HUMAN_REVIEW,
                None,
                None,
                started,
            )
            artifacts.persist_result(result)
            return result

        attempts: list[RepairAttempt] = []
        feedback: RepairFeedback | None = None
        final_verification: VerificationResult | None = None
        winning_attempt: int | None = None
        final_status = MigrationStatus.UNRESOLVED

        for number in range(1, self.config.max_repair_attempts + 1):
            LOGGER.info("Starting repair attempt %d", number)
            attempt_started = time.monotonic()
            attempt_directory = artifacts.attempt_directory(number)
            try:
                with WorkspaceManager(
                    repository, f"{planning.plan.run_id}-repair-{number}"
                ) as workspaces:
                    workspace = workspaces.create(
                        task.updated_commit, WorkspaceKind.REPAIR
                    )
                    if repository_status(workspace):
                        raise RepairError(
                            "repair workspace was not clean at updated commit"
                        )
                    baseline = self.patch_analyzer.capture_baseline(workspace.path)
                    request = build_repair_request(
                        planning.repair_context, number, feedback
                    )
                    artifacts.persist_request(number, request.instruction)
                    provider_result = self.provider.repair(workspace, request)
                    artifacts.persist_provider_output(
                        number, provider_result.raw_output
                    )

                    patch = self.patch_analyzer.analyze(
                        workspace.path, baseline, planning.plan
                    )
                    artifacts.persist_patch(number, patch)
                    attempt = self._evaluate_attempt(
                        task,
                        planning,
                        workspace,
                        attempt_directory,
                        number,
                        provider_result,
                        feedback,
                        patch,
                        attempt_started,
                    )
                    attempts.append(attempt)
                    artifacts.persist_attempt(attempt)
            except (WorkspaceError, PatchAnalysisError, OSError) as error:
                raise RepairError(f"repair attempt {number} failed: {error}") from error

            feedback = attempt.feedback
            final_verification = attempt.verification or final_verification
            if attempt.status is RepairAttemptStatus.VERIFIED:
                winning_attempt = number
                final_status = MigrationStatus.VERIFIED_MIGRATION
                artifacts.persist_final_patch(attempt.patch_analysis)
                break
            if (
                attempt.verification is not None
                and attempt.verification.status
                is VerificationStatus.NEEDS_HUMAN_REVIEW
            ):
                final_status = MigrationStatus.NEEDS_HUMAN_REVIEW
                break
            if _must_stop(attempt):
                break

        result = self._finish(
            planning,
            tuple(attempts),
            final_status,
            winning_attempt,
            final_verification,
            started,
        )
        artifacts.persist_result(result)
        return result

    def _evaluate_attempt(
        self,
        task: TaskSpec,
        planning: MigrationPlanningResult,
        workspace: RepositoryWorkspace,
        attempt_directory: Path,
        number: int,
        provider_result: RepairProviderResult,
        feedback_used: RepairFeedback | None,
        patch: PatchAnalysis,
        started: float,
    ) -> RepairAttempt:
        if provider_result.status is not RepairProviderStatus.SUCCESS:
            status = (
                RepairAttemptStatus.TIMEOUT
                if provider_result.status is RepairProviderStatus.TIMEOUT
                else RepairAttemptStatus.PROVIDER_ERROR
            )
            next_feedback = _simple_feedback(
                number, status, patch.changed_files, provider_result.summary
            )
            return _attempt(
                number, status, provider_result, feedback_used, patch, next_feedback,
                started,
            )
        if not patch.has_changes:
            status = RepairAttemptStatus.NO_CHANGES
            next_feedback = _simple_feedback(
                number, status, (), "provider produced no Git-visible project changes"
            )
            return _attempt(
                number, status, provider_result, feedback_used, patch, next_feedback,
                started,
            )
        if patch.fatal_issues:
            status = RepairAttemptStatus.PATCH_REJECTED
            next_feedback = RepairFeedback(
                number,
                status,
                patch.changed_files,
                "patch rejected before Maven execution",
                safety_issues=patch.fatal_issues,
            )
            return _attempt(
                number, status, provider_result, feedback_used, patch, next_feedback,
                started,
            )

        dependency = self.dependency_validator.validate(
            task,
            planning.plan,
            workspace,
            attempt_directory / "resolved-dependencies.txt",
        )
        if (
            dependency.execution.status is not ExecutionStatus.PASS
            or not dependency.target_retained
            or not dependency.causal_dependency_retained
        ):
            status = RepairAttemptStatus.PATCH_REJECTED
            next_feedback = RepairFeedback(
                number,
                status,
                patch.changed_files,
                "dependency guard rejected the candidate patch",
                safety_issues=dependency.issues,
            )
            return _attempt(
                number,
                status,
                provider_result,
                feedback_used,
                patch,
                next_feedback,
                started,
                dependency=dependency,
            )

        compile_result = self.maven.execute_lifecycle(workspace, "compile")
        if compile_result.status is not ExecutionStatus.PASS:
            status = (
                RepairAttemptStatus.TIMEOUT
                if compile_result.status is ExecutionStatus.TIMEOUT
                else RepairAttemptStatus.EXECUTION_ERROR
                if compile_result.status is ExecutionStatus.ERROR
                else RepairAttemptStatus.COMPILE_FAILED
            )
            next_feedback = self._execution_feedback(
                number, status, patch.changed_files, compile_result, workspace
            )
            return _attempt(
                number, status, provider_result, feedback_used, patch, next_feedback,
                started, dependency=dependency, compile_result=compile_result,
            )

        test_result = self.maven.execute_lifecycle(workspace, "test")
        if test_result.status is not ExecutionStatus.PASS:
            status = (
                RepairAttemptStatus.TIMEOUT
                if test_result.status is ExecutionStatus.TIMEOUT
                else RepairAttemptStatus.EXECUTION_ERROR
                if test_result.status is ExecutionStatus.ERROR
                else RepairAttemptStatus.TEST_FAILED
            )
            next_feedback = self._execution_feedback(
                number, status, patch.changed_files, test_result, workspace
            )
            return _attempt(
                number, status, provider_result, feedback_used, patch, next_feedback,
                started, dependency=dependency, compile_result=compile_result,
                test_result=test_result,
            )

        verification = self.verifier.verify(
            dependency, compile_result, test_result, patch
        )
        status = (
            RepairAttemptStatus.VERIFIED
            if verification.status is VerificationStatus.VERIFIED_MIGRATION
            else RepairAttemptStatus.VERIFICATION_FAILED
        )
        next_feedback = (
            None
            if status is RepairAttemptStatus.VERIFIED
            else RepairFeedback(
                number,
                status,
                patch.changed_files,
                "independent verification did not accept the patch",
                safety_issues=verification.reasons,
            )
        )
        return _attempt(
            number, status, provider_result, feedback_used, patch, next_feedback,
            started, dependency=dependency, compile_result=compile_result,
            test_result=test_result, verification=verification,
        )

    def _execution_feedback(
        self,
        number: int,
        status: RepairAttemptStatus,
        changed_files: tuple[Path, ...],
        execution: ExecutionResult,
        workspace: RepositoryWorkspace,
    ) -> RepairFeedback:
        failures = self.failure_parser.parse(execution)
        primary = failures[0] if failures else None
        if primary is not None:
            primary = self.source_locator.localize(primary, workspace.path)
        log = execution_log_text(execution)
        return RepairFeedback(
            number,
            status,
            changed_files,
            f"independent Maven execution returned {execution.status.value}",
            primary_failure=primary,
            bounded_excerpt=log[-MAX_FEEDBACK_LOG_CHARS:],
        )

    def _finish(
        self,
        planning: MigrationPlanningResult,
        attempts: tuple[RepairAttempt, ...],
        status: MigrationStatus,
        winning_attempt: int | None,
        verification: VerificationResult | None,
        started: float,
    ) -> RepairResult:
        duration = time.monotonic() - started
        report = MigrationReport(
            task=planning.task,
            status=status,
            evidence=planning.evidence,
            hypothesis=planning.diagnosis.primary_hypothesis,
            attempts=attempts,
            verification=verification,
            diagnosis_summary=planning.diagnosis.summary,
            plan_summary=planning.plan.summary,
            winning_attempt=winning_attempt,
            duration_seconds=duration,
            artifact_directory=planning.plan.artifact_directory,
        )
        return RepairResult(
            run_id=planning.plan.run_id,
            status=status,
            artifact_directory=planning.plan.artifact_directory,
            attempts=attempts,
            winning_attempt=winning_attempt,
            verification=verification,
            total_duration_seconds=duration,
            report=report,
        )


class RepairArtifacts:
    """Persist every attempt and final objective repair result externally."""

    def __init__(self, run_directory: Path) -> None:
        self.run_directory = Path(run_directory)
        self.attempts_directory = self.run_directory / "attempts"
        self.attempts_directory.mkdir(parents=True, exist_ok=True)

    def attempt_directory(self, number: int) -> Path:
        path = self.attempts_directory / str(number)
        path.mkdir(parents=False, exist_ok=False)
        return path

    def persist_request(self, number: int, instruction: str) -> None:
        self._write_text(number, "repair-request.txt", instruction)

    def persist_provider_output(self, number: int, output: str) -> None:
        self._write_text(number, "provider-output.txt", output)

    def persist_patch(self, number: int, patch: PatchAnalysis) -> None:
        self._write_text(number, "patch.diff", patch.patch)
        self._write_json(number, "patch-analysis.json", patch)

    def persist_attempt(self, attempt: RepairAttempt) -> None:
        number = attempt.attempt_number
        if attempt.dependency_validation is not None:
            self._write_text(
                number,
                "dependency-validation.log",
                execution_log_text(attempt.dependency_validation.execution),
            )
        if attempt.compile_result is not None:
            self._write_text(
                number, "compile.log", execution_log_text(attempt.compile_result)
            )
        if attempt.test_result is not None:
            self._write_text(
                number, "test.log", execution_log_text(attempt.test_result)
            )
        if attempt.feedback is not None:
            self._write_json(number, "feedback.json", attempt.feedback)
        if attempt.verification is not None:
            self._write_json(number, "verification.json", attempt.verification)
        self._write_json(number, "attempt.json", attempt)

    def persist_final_patch(self, patch: PatchAnalysis | None) -> None:
        if patch is not None:
            (self.run_directory / "final.patch").write_text(
                patch.patch, encoding="utf-8"
            )

    def persist_result(self, result: RepairResult) -> None:
        (self.run_directory / "repair-result.json").write_text(
            json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if result.verification is not None:
            (self.run_directory / "verification.json").write_text(
                json.dumps(_jsonable(result.verification), indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
        if result.report is not None:
            (self.run_directory / "migration-report.txt").write_text(
                render_migration_report(result.report), encoding="utf-8"
            )

    def _write_text(self, number: int, filename: str, value: str) -> None:
        (self.attempts_directory / str(number) / filename).write_text(
            value, encoding="utf-8"
        )

    def _write_json(self, number: int, filename: str, value: object) -> None:
        self._write_text(
            number,
            filename,
            json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        )


def repository_status(workspace: RepositoryWorkspace) -> str:
    """Return repair-worktree status through the centralized Git abstraction."""
    from bumpshield.repo.git import GitRepository

    return GitRepository(workspace.path).status_porcelain()


def _attempt(
    number: int,
    status: RepairAttemptStatus,
    provider_result: RepairProviderResult,
    feedback_used: RepairFeedback | None,
    patch: PatchAnalysis,
    feedback: RepairFeedback | None,
    started: float,
    *,
    dependency: DependencyValidationResult | None = None,
    compile_result: ExecutionResult | None = None,
    test_result: ExecutionResult | None = None,
    verification: VerificationResult | None = None,
) -> RepairAttempt:
    execution = test_result or compile_result or (
        dependency.execution if dependency is not None else ExecutionResult(
            ExecutionStatus.ERROR, detail="Maven execution was not reached"
        )
    )
    return RepairAttempt(
        attempt_number=number,
        execution=execution,
        status=status,
        provider_result=provider_result,
        feedback_used=feedback_used,
        modified_files=patch.changed_files,
        lines_added=patch.stats.lines_added,
        lines_removed=patch.stats.lines_removed,
        patch_path=Path("attempts") / str(number) / "patch.diff",
        patch_analysis=patch,
        compile_result=compile_result,
        test_result=test_result,
        dependency_validation=dependency,
        verification=verification,
        feedback=feedback,
        duration_seconds=time.monotonic() - started,
    )


def _simple_feedback(
    number: int,
    status: RepairAttemptStatus,
    changed_files: tuple[Path, ...],
    summary: str,
) -> RepairFeedback:
    return RepairFeedback(number, status, changed_files, summary)


def _must_stop(attempt: RepairAttempt) -> bool:
    if attempt.provider_result is not None and (
        attempt.provider_result.status is RepairProviderStatus.UNAVAILABLE
    ):
        return True
    if attempt.status is RepairAttemptStatus.PATCH_REJECTED:
        return True
    if attempt.status is RepairAttemptStatus.EXECUTION_ERROR:
        return True
    return False


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    raise TypeError(f"unsupported repair artifact value: {type(value).__name__}")
