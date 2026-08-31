"""Case validation, strategy isolation, resume, and benchmark orchestration."""

from __future__ import annotations

import json
import logging
import platform
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from bumpshield import __version__
from bumpshield.analysis.dependency_diff import DependencyAnalysisError, DependencyAnalyzer
from bumpshield.analysis.reproducer import RegressionReproducer, ReproductionError
from bumpshield.config import BumpShieldConfig
from bumpshield.evaluation.metrics import summarize_benchmark
from bumpshield.evaluation.dataset import DatasetFreezeError, verify_dataset_lock
from bumpshield.evaluation.failures import is_global_provider_failure
from bumpshield.evaluation.freeze import (
    FrozenConfigError,
    VERIFICATION_POLICY_VERSION,
    load_frozen_config,
    runtime_configuration,
    stable_digest,
    validate_frozen_runtime,
)
from bumpshield.evaluation.models import (
    BenchmarkCase,
    BenchmarkCaseResult,
    BenchmarkCaseType,
    BenchmarkDryRun,
    BenchmarkRunStatus,
    BenchmarkRunResult,
    BenchmarkSource,
    BenchmarkSuite,
    BenchmarkValidation,
    BenchmarkValidationStatus,
    EnvironmentMetadata,
    EvaluationFinalStatus,
    FailureReason,
    FailureDomain,
    ProviderMetadata,
    ProviderFailureKind,
    StrategyId,
)
from bumpshield.evaluation.report import BenchmarkReporter
from bumpshield.evaluation.serialization import jsonable
from bumpshield.evaluation.strategies import (
    BumpShieldStrategy,
    DirectOneShotStrategy,
    DirectRetryStrategy,
    EvaluationStrategy,
)
from bumpshield.evaluation.schedule import counterbalanced_schedule
from bumpshield.execution.command_runner import CommandExecutionError, CommandRunner
from bumpshield.models import MigrationKind, ReproductionStatus
from bumpshield.run import generate_run_id, require_external_path

LOGGER = logging.getLogger(__name__)


class BenchmarkError(RuntimeError):
    """Raised when the benchmark harness itself cannot run safely."""


class CaseValidation(Protocol):
    """Reusable deterministic benchmark validity boundary."""

    def validate(self, case: BenchmarkCase) -> BenchmarkValidation:
        """Validate base/updated behavior and target resolution."""
        ...


class BenchmarkCaseValidator:
    """Reuse reproduction and dependency analysis for case preconditions."""

    def __init__(
        self,
        config: BumpShieldConfig,
        reproducer: RegressionReproducer | None = None,
        dependency_analyzer: DependencyAnalyzer | None = None,
    ) -> None:
        self.reproducer = reproducer or RegressionReproducer(config=config)
        self.dependency_analyzer = dependency_analyzer or DependencyAnalyzer(
            config=config
        )

    def validate(self, case: BenchmarkCase) -> BenchmarkValidation:
        artifacts: list[Path] = []
        try:
            reproduction = self.reproducer.reproduce(case.task)
            artifacts.append(reproduction.artifact_directory)
            if reproduction.status is not ReproductionStatus.CONFIRMED:
                return BenchmarkValidation(
                    BenchmarkValidationStatus.INVALID_CASE,
                    f"regression reproduction returned {reproduction.status.value}",
                    reproduction.status.value,
                    None,
                    tuple(artifacts),
                )
            dependencies = self.dependency_analyzer.analyze(case.task)
            artifacts.append(dependencies.artifact_directory)
            matched = bool(dependencies.diff.target and dependencies.diff.target.matched)
            if not matched:
                return BenchmarkValidation(
                    BenchmarkValidationStatus.INVALID_CASE,
                    "declared target versions do not match resolved base/updated versions",
                    reproduction.status.value,
                    False,
                    tuple(artifacts),
                )
            return BenchmarkValidation(
                BenchmarkValidationStatus.VALID,
                None,
                reproduction.status.value,
                True,
                tuple(artifacts),
            )
        except (ReproductionError, DependencyAnalysisError) as error:
            return BenchmarkValidation(
                BenchmarkValidationStatus.INVALID_CASE,
                str(error),
                None,
                None,
                tuple(artifacts),
            )


class BenchmarkRunner:
    """Run validated cases without changing existing diagnosis/repair components."""

    def __init__(
        self,
        config: BumpShieldConfig | None = None,
        validator: CaseValidation | None = None,
        strategies: Mapping[StrategyId, EvaluationStrategy] | None = None,
        reporter: BenchmarkReporter | None = None,
        runner: CommandRunner | None = None,
        progress: Callable[[int, int, BenchmarkCase, StrategyId, str], None]
        | None = None,
    ) -> None:
        self.config = config or BumpShieldConfig()
        self.runner = runner or CommandRunner()
        self.validator = validator or BenchmarkCaseValidator(self.config)
        self.strategies = dict(
            strategies
            or {
                StrategyId.DIRECT_ONE_SHOT: DirectOneShotStrategy(self.config),
                StrategyId.DIRECT_RETRY: DirectRetryStrategy(self.config),
                StrategyId.BUMPSHIELD: BumpShieldStrategy(self.config),
            }
        )
        self.reporter = reporter or BenchmarkReporter()
        self.progress = progress

    def dry_run(self, suite: BenchmarkSuite) -> BenchmarkDryRun:
        """Return maximum provider calls without Git, Maven, or provider execution."""
        if suite.dataset_lock_path is not None:
            try:
                verify_dataset_lock(suite)
            except DatasetFreezeError as error:
                raise BenchmarkError(str(error)) from error
        missing = tuple(strategy for strategy in suite.strategies if strategy not in self.strategies)
        if missing:
            raise BenchmarkError(
                "unsupported benchmark strategies: "
                + ", ".join(item.value for item in missing)
            )
        maximum = sum(
            self.strategies[strategy].maximum_provider_calls
            for strategy in suite.strategies
        ) * len(suite.cases) * suite.trials
        schedule = counterbalanced_schedule(suite)
        return BenchmarkDryRun(
            suite_id=suite.id,
            case_count=len(suite.cases),
            strategies=suite.strategies,
            trials=suite.trials,
            planned_trials=len(suite.cases) * len(suite.strategies) * suite.trials,
            maximum_provider_calls=maximum,
            provider_call_budgets=tuple(
                (strategy, self.strategies[strategy].maximum_provider_calls)
                for strategy in suite.strategies
            ),
            schedule=schedule,
        )

    def run(
        self,
        suite: BenchmarkSuite,
        *,
        resume_run_id: str | None = None,
        rerun: bool = False,
    ) -> BenchmarkRunResult:
        """Persist each result immediately so an interrupted run can resume."""
        preview = self.dry_run(suite)
        if all(
            shutil.which(self.config.repair_provider_executable) is None
            for _ in suite.strategies
        ):
            raise BenchmarkError(
                f"repair provider unavailable: {self.config.repair_provider_executable}"
            )
        run_id = resume_run_id or generate_run_id()
        directory = self.config.benchmark_directory(run_id).resolve()
        for case in suite.cases:
            try:
                require_external_path(directory, case.task.repository.resolve())
            except Exception as error:
                raise BenchmarkError(str(error)) from error
        if resume_run_id:
            if not directory.is_dir():
                raise BenchmarkError(f"benchmark run does not exist: {directory}")
        else:
            try:
                directory.mkdir(parents=True, exist_ok=False)
            except OSError as error:
                raise BenchmarkError(
                    f"could not create benchmark directory {directory}: {error}"
                ) from error
        effective_configuration = runtime_configuration(
            suite, self.strategies, self.config
        )
        try:
            if suite.evaluation_config_path is not None:
                frozen = load_frozen_config(suite.evaluation_config_path)
                validate_frozen_runtime(frozen, effective_configuration)
                config_hash = frozen.sha256
            else:
                config_hash = stable_digest(effective_configuration)
        except FrozenConfigError as error:
            raise BenchmarkError(str(error)) from error
        self._check_resume_configuration(directory, resume_run_id, config_hash)
        self._persist_configuration(
            directory, suite, preview, effective_configuration, config_hash
        )
        if suite.dataset_lock_path is not None:
            shutil.copyfile(suite.dataset_lock_path, directory / "dataset-lock.json")
        environment = collect_environment(self.runner, self.config)
        provider = collect_provider_metadata(self.runner, self.config)
        self._warn_provider_version_drift(directory, resume_run_id, provider)
        results: list[BenchmarkCaseResult] = []
        total = preview.planned_trials
        cases = {case.id: case for case in suite.cases}
        validations: dict[str, BenchmarkValidation] = {}
        status = BenchmarkRunStatus.RUNNING
        self._persist_run_state(directory, status, total, results, config_hash)
        for ordinal, entry in enumerate(preview.schedule, start=1):
            case = cases[entry.case_id]
            strategy = self.strategies[entry.strategy]
            result_path = self._result_path(
                directory, case.id, entry.strategy, entry.trial
            )
            newly_executed = False
            if result_path.is_file() and not rerun:
                result = load_case_result(result_path)
                self._progress(
                    ordinal,
                    total,
                    case,
                    entry.strategy,
                    "RESUMED",
                )
            else:
                validation = validations.get(case.id)
                if validation is None:
                    validation = self.validator.validate(case)
                    validations[case.id] = validation
                    self._persist_validation(directory, case, validation)
                if validation.status is BenchmarkValidationStatus.INVALID_CASE:
                    result = invalid_case_result(
                        run_id, case, entry.strategy, entry.trial, validation.reason
                    )
                else:
                    try:
                        result = strategy.run(case, run_id, entry.trial)
                    except Exception as error:
                        LOGGER.exception(
                            "Benchmark strategy %s failed for %s",
                            entry.strategy,
                            case.id,
                        )
                        result = execution_error_result(
                            run_id, case, entry.strategy, entry.trial, str(error)
                        )
                    newly_executed = True
                result = replace(
                    result,
                    schema_version=2,
                    execution_position=entry.execution_position,
                    attempt_budget=strategy.maximum_provider_calls,
                    benchmark_config_hash=config_hash,
                    verification_policy_version=VERIFICATION_POLICY_VERSION,
                )
                self._persist_case_result(result_path, result)
                self._progress(
                    ordinal,
                    total,
                    case,
                    entry.strategy,
                    result.final_status.value,
                )
            results.append(result)
            self._persist_run_state(directory, status, total, results, config_hash)
            if newly_executed and is_global_provider_failure(
                result.provider_failure_kind
            ):
                status = BenchmarkRunStatus.PAUSED_PROVIDER_UNAVAILABLE
                break
        if status is BenchmarkRunStatus.RUNNING:
            status = BenchmarkRunStatus.COMPLETED
        ordered = tuple(sorted(results, key=_result_key))
        attempted = sum(
            item.validation_status is BenchmarkValidationStatus.VALID
            for item in ordered
        )
        completed = len(ordered)
        unexecuted = total - completed
        summary = summarize_benchmark(
            run_id,
            suite.id,
            len(suite.cases),
            ordered,
            run_status=status,
            planned_trials=total,
        )
        self.reporter.persist(directory, ordered, summary, environment, provider)
        self._persist_run_state(directory, status, total, results, config_hash)
        return BenchmarkRunResult(
            run_id,
            suite.id,
            directory,
            ordered,
            summary,
            status,
            total,
            attempted,
            completed,
            unexecuted,
            config_hash,
        )

    def _persist_configuration(
        self,
        directory: Path,
        suite: BenchmarkSuite,
        preview: BenchmarkDryRun,
        effective_configuration: dict[str, object],
        config_hash: str,
    ) -> None:
        data = {
            "suite": jsonable(suite),
            "dry_run": jsonable(preview),
            "effective_configuration": effective_configuration,
            "benchmark_config_hash": config_hash,
            "strategy_order_policy": "counterbalanced-rotation-v1",
        }
        (directory / "benchmark-config.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (directory / "execution-schedule.json").write_text(
            json.dumps(jsonable(preview.schedule), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _check_resume_configuration(
        self, directory: Path, resume_run_id: str | None, config_hash: str
    ) -> None:
        if resume_run_id is None:
            return
        path = directory / "benchmark-config.json"
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        previous = existing.get("benchmark_config_hash")
        if previous is not None and previous != config_hash:
            raise BenchmarkError(
                "benchmark configuration changed; refusing mixed-config resume"
            )

    def _persist_run_state(
        self,
        directory: Path,
        status: BenchmarkRunStatus,
        planned: int,
        results: list[BenchmarkCaseResult],
        config_hash: str,
    ) -> None:
        completed = len(results)
        attempted = sum(
            item.validation_status is BenchmarkValidationStatus.VALID
            for item in results
        )
        data = {
            "schema_version": 2,
            "status": status.value,
            "planned_trials": planned,
            "attempted_trials": attempted,
            "completed_trials": completed,
            "unexecuted_trials": planned - completed,
            "benchmark_config_hash": config_hash,
        }
        (directory / "benchmark-run.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _warn_provider_version_drift(
        self,
        directory: Path,
        resume_run_id: str | None,
        provider: ProviderMetadata,
    ) -> None:
        if resume_run_id is None:
            return
        try:
            previous = json.loads(
                (directory / "provider.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return
        if previous.get("version") != provider.version:
            LOGGER.warning(
                "provider version drift on resume: %s -> %s",
                previous.get("version"),
                provider.version,
            )

    def _persist_validation(
        self, directory: Path, case: BenchmarkCase, validation: BenchmarkValidation
    ) -> None:
        path = directory / "cases" / case.id
        path.mkdir(parents=True, exist_ok=True)
        (path / "validation.json").write_text(
            json.dumps(jsonable(validation), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _result_path(
        self,
        directory: Path,
        case_id: str,
        strategy: StrategyId,
        trial: int,
    ) -> Path:
        path = directory / "cases" / case_id / strategy.value / str(trial)
        path.mkdir(parents=True, exist_ok=True)
        return path / "result.json"

    def _existing_result_path(
        self,
        directory: Path,
        case_id: str,
        strategy: StrategyId,
        trial: int,
    ) -> Path:
        return (
            directory
            / "cases"
            / case_id
            / strategy.value
            / str(trial)
            / "result.json"
        )

    def _persist_case_result(
        self, path: Path, result: BenchmarkCaseResult
    ) -> None:
        path.write_text(
            json.dumps(jsonable(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _progress(
        self,
        position: int,
        total: int,
        case: BenchmarkCase,
        strategy: StrategyId,
        status: str,
    ) -> None:
        if self.progress is not None:
            self.progress(position, total, case, strategy, status)


def invalid_case_result(
    benchmark_run_id: str,
    case: BenchmarkCase,
    strategy: StrategyId,
    trial: int,
    reason: str | None,
) -> BenchmarkCaseResult:
    """Create explicit invalid row excluded from the VRR denominator."""
    return BenchmarkCaseResult(
        benchmark_run_id,
        case.id,
        case.case_type,
        case.source,
        case.ground_truth.failure_kind if case.ground_truth else None,
        strategy,
        trial,
        BenchmarkValidationStatus.INVALID_CASE,
        EvaluationFinalStatus.INVALID_CASE,
        False,
        failure_reason=FailureReason.INFRASTRUCTURE_ERROR if reason else None,
        failure_domain=FailureDomain.CASE_VALIDATION,
    )


def execution_error_result(
    benchmark_run_id: str,
    case: BenchmarkCase,
    strategy: StrategyId,
    trial: int,
    reason: str,
) -> BenchmarkCaseResult:
    """Isolate one strategy infrastructure failure and continue the suite."""
    del reason
    return BenchmarkCaseResult(
        benchmark_run_id,
        case.id,
        case.case_type,
        case.source,
        case.ground_truth.failure_kind if case.ground_truth else None,
        strategy,
        trial,
        BenchmarkValidationStatus.VALID,
        EvaluationFinalStatus.EXECUTION_ERROR,
        False,
        failure_reason=FailureReason.INFRASTRUCTURE_ERROR,
        failure_domain=FailureDomain.INFRASTRUCTURE,
    )


def load_case_result(path: Path) -> BenchmarkCaseResult:
    """Load one complete persisted row for resume behavior."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return BenchmarkCaseResult(
            benchmark_run_id=data["benchmark_run_id"],
            case_id=data["case_id"],
            case_type=BenchmarkCaseType(data["case_type"]),
            case_source=BenchmarkSource(data["case_source"]),
            failure_kind=(
                MigrationKind(data["failure_kind"])
                if data.get("failure_kind")
                else None
            ),
            strategy=StrategyId(data["strategy"]),
            trial=data["trial"],
            validation_status=BenchmarkValidationStatus(data["validation_status"]),
            final_status=EvaluationFinalStatus(data["final_status"]),
            verified=data["verified"],
            root_cause_correct=data.get("root_cause_correct"),
            api_change_correct=data.get("api_change_correct"),
            diagnosis_status=data.get("diagnosis_status"),
            diagnosis_strength=data.get("diagnosis_strength"),
            diagnosis_score=data.get("diagnosis_score"),
            plan_status=data.get("plan_status"),
            diagnosed_dependency=data.get("diagnosed_dependency"),
            attempt_count=data.get("attempt_count", 0),
            provider_calls=data.get("provider_calls", 0),
            total_duration_seconds=data.get("total_duration_seconds", 0.0),
            diagnosis_duration_seconds=data.get("diagnosis_duration_seconds"),
            provider_duration_seconds=data.get("provider_duration_seconds", 0.0),
            compile_duration_seconds=data.get("compile_duration_seconds", 0.0),
            test_duration_seconds=data.get("test_duration_seconds", 0.0),
            files_changed=data.get("files_changed", 0),
            lines_added=data.get("lines_added", 0),
            lines_removed=data.get("lines_removed", 0),
            verification_status=data.get("verification_status"),
            failure_reason=(
                FailureReason(data["failure_reason"])
                if data.get("failure_reason")
                else None
            ),
            run_id=data.get("run_id"),
            run_artifact_path=(
                Path(data["run_artifact_path"])
                if data.get("run_artifact_path")
                else None
            ),
            provider_input_tokens=data.get("provider_input_tokens"),
            provider_output_tokens=data.get("provider_output_tokens"),
            provider_cached_tokens=data.get("provider_cached_tokens"),
            provider_cost=data.get("provider_cost"),
            schema_version=data.get("schema_version", 1),
            execution_position=data.get("execution_position"),
            attempt_budget=data.get("attempt_budget"),
            winning_attempt=data.get("winning_attempt"),
            failure_domain=(
                FailureDomain(data["failure_domain"])
                if data.get("failure_domain")
                else None
            ),
            provider_failure_kind=(
                ProviderFailureKind(data["provider_failure_kind"])
                if data.get("provider_failure_kind")
                else None
            ),
            benchmark_config_hash=data.get("benchmark_config_hash"),
            verification_policy_version=data.get("verification_policy_version"),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise BenchmarkError(f"invalid resumed result {path}: {error}") from error


def collect_provider_metadata(
    runner: CommandRunner, config: BumpShieldConfig
) -> ProviderMetadata:
    """Record one provider contract shared across strategies."""
    version = _version(runner, (config.repair_provider_executable, "--version"))
    return ProviderMetadata(
        provider="codex-cli",
        executable=config.repair_provider_executable,
        version=version,
        model=None,
        timeout_seconds=config.repair_provider_timeout_seconds,
        maximum_attempts=config.max_repair_attempts,
    )


def collect_environment(
    runner: CommandRunner, config: BumpShieldConfig
) -> EnvironmentMetadata:
    """Collect best-effort versions without making missing tools fatal."""
    return EnvironmentMetadata(
        platform=platform.platform(),
        python=sys.version.splitlines()[0],
        git=_version(runner, ("git", "--version")),
        java=_version(runner, ("java", "-version")),
        maven=_version(runner, ("mvn", "-version")),
        codex=_version(runner, (config.repair_provider_executable, "--version")),
        bumpshield_version=__version__,
        bumpshield_commit=_bumpshield_commit(runner),
    )


def _version(runner: CommandRunner, command: tuple[str, ...]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        result = runner.run(command, cwd=Path.cwd(), timeout=10)
    except CommandExecutionError:
        return None
    if result.exit_code != 0:
        return None
    text = result.stdout.strip() or result.stderr.strip()
    return text.splitlines()[0] if text else None


def _bumpshield_commit(runner: CommandRunner) -> str | None:
    try:
        result = runner.run(("git", "rev-parse", "HEAD"), cwd=Path.cwd(), timeout=10)
    except CommandExecutionError:
        return None
    return result.stdout.strip() if result.exit_code == 0 else None


def _result_key(result: BenchmarkCaseResult) -> tuple[str, str, int]:
    return result.case_id, result.strategy.value, result.trial
