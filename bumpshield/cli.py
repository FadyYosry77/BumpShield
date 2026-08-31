"""Command-line interface for BumpShield."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from bumpshield import __version__
from bumpshield.agent.investigator import CausalDiagnoser, DiagnosisError
from bumpshield.agent.repair_engine import RepairEngine, RepairError
from bumpshield.agent.repairer import MigrationPlanningService, PlanningError
from bumpshield.analysis.dependency_diff import (
    DependencyAnalysisError,
    DependencyAnalyzer,
)
from bumpshield.analysis.api_diff import ApiEvidenceAnalysisError, ApiEvidenceAnalyzer
from bumpshield.analysis.failure_parser import FailureAnalysisError, FailureAnalyzer
from bumpshield.analysis.reproducer import RegressionReproducer, ReproductionError
from bumpshield.config import BumpShieldConfig
from bumpshield.models import (
    AffectedLocationKind,
    ApiAnalysisStatus,
    ApiEvidenceAnalysisResult,
    CausalDiagnosis,
    DiagnosisStatus,
    DependencyAnalysisResult,
    DependencyChange,
    DependencyChangeKind,
    FailureAnalysisResult,
    FailureAnalysisStatus,
    MigrationPlanningResult,
    MigrationStatus,
    PlanStatus,
    RepairProviderStatus,
    RepairResult,
    ReproductionResult,
    ReproductionStatus,
)
from bumpshield.task_io import TaskSpecLoadError, load_task_spec
from bumpshield.evaluation.loader import BenchmarkLoadError, load_benchmark_suite
from bumpshield.evaluation.models import BenchmarkRunResult
from bumpshield.evaluation.final_report import FinalResearchReporter
from bumpshield.evaluation.runner import BenchmarkError, BenchmarkRunner
from bumpshield.evaluation.dataset import (
    DatasetFreezeError,
    FinalDatasetService,
    persist_validation,
    verify_dataset_lock,
    write_dataset_lock,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the BumpShield argument parser."""
    parser = argparse.ArgumentParser(
        prog="bumpshield",
        description="Causal dependency migration agent",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("version", help="show installed BumpShield version")
    reproduce_parser = subparsers.add_parser(
        "reproduce",
        help="reproduce a base-versus-updated regression",
    )
    reproduce_parser.add_argument("task_json", type=Path, help="path to task JSON")
    reproduce_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    dependencies_parser = subparsers.add_parser(
        "dependencies",
        help="compare resolved Maven dependencies between revisions",
    )
    dependencies_parser.add_argument("task_json", type=Path, help="path to task JSON")
    dependencies_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    failures_parser = subparsers.add_parser(
        "failures",
        help="parse and localize updated-revision build failures",
    )
    failures_parser.add_argument("task_json", type=Path, help="path to task JSON")
    failures_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    evidence_parser = subparsers.add_parser(
        "evidence",
        help="collect targeted dependency ownership and Java API evidence",
    )
    evidence_parser.add_argument("task_json", type=Path, help="path to task JSON")
    evidence_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    diagnose_parser = subparsers.add_parser(
        "diagnose",
        help="construct deterministic causal hypotheses from local evidence",
    )
    diagnose_parser.add_argument("task_json", type=Path, help="path to task JSON")
    diagnose_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    plan_parser = subparsers.add_parser(
        "plan",
        help="create a deterministic bounded migration plan",
    )
    plan_parser.add_argument("task_json", type=Path, help="path to task JSON")
    plan_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    repair_parser = subparsers.add_parser(
        "repair",
        help="repair and independently verify a planned migration",
    )
    repair_parser.add_argument("task_json", type=Path, help="path to task JSON")
    repair_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    benchmark_parser = subparsers.add_parser(
        "benchmark",
        help="evaluate repair strategies with independent verification",
    )
    benchmark_parser.add_argument(
        "suite_json", type=Path, help="path to benchmark suite JSON"
    )
    benchmark_parser.add_argument(
        "--state-dir",
        type=Path,
        help="external directory for persistent BumpShield state",
    )
    benchmark_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show cases and maximum provider calls without execution",
    )
    benchmark_parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="continue one external benchmark run",
    )
    benchmark_parser.add_argument(
        "--rerun",
        action="store_true",
        help="rerun completed case-strategy trials when resuming",
    )
    benchmark_parser.add_argument(
        "--validate-only",
        action="store_true",
        help="validate all cases without invoking repair providers",
    )
    benchmark_parser.add_argument(
        "--write-lock",
        type=Path,
        help="write final dataset lock after successful --validate-only",
    )
    benchmark_parser.add_argument(
        "--verify-freeze",
        action="store_true",
        help="verify final config, manifests, commits, composition, and dataset lock",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the BumpShield CLI."""
    parser = build_parser()
    arguments = parser.parse_args(argv)

    if arguments.command == "version":
        print(__version__)
    elif arguments.command == "reproduce":
        try:
            task = load_task_spec(arguments.task_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            result = RegressionReproducer(config=config).reproduce(task)
        except (TaskSpecLoadError, ReproductionError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_reproduction(result)
        return reproduction_exit_code(result.status)
    elif arguments.command == "dependencies":
        try:
            task = load_task_spec(arguments.task_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            dependency_result = DependencyAnalyzer(config=config).analyze(task)
        except (TaskSpecLoadError, DependencyAnalysisError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_dependency_analysis(dependency_result)
        return dependency_exit_code(dependency_result)
    elif arguments.command == "failures":
        try:
            task = load_task_spec(arguments.task_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            failure_result = FailureAnalyzer(config=config).analyze(task)
        except (TaskSpecLoadError, FailureAnalysisError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_failure_analysis(failure_result)
        return failure_exit_code(failure_result.status)
    elif arguments.command == "evidence":
        try:
            task = load_task_spec(arguments.task_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            evidence_result = ApiEvidenceAnalyzer(config=config).analyze(task)
        except (TaskSpecLoadError, ApiEvidenceAnalysisError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_api_evidence(evidence_result)
        return api_evidence_exit_code(evidence_result.status)
    elif arguments.command == "diagnose":
        try:
            task = load_task_spec(arguments.task_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            diagnosis = CausalDiagnoser(config=config).diagnose(task)
        except (TaskSpecLoadError, DiagnosisError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_diagnosis(diagnosis)
        return diagnosis_exit_code(diagnosis.status)
    elif arguments.command == "plan":
        try:
            task = load_task_spec(arguments.task_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            planning = MigrationPlanningService(config=config).plan(task)
        except (TaskSpecLoadError, PlanningError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_migration_plan(planning)
        return plan_exit_code(planning.plan.status)
    elif arguments.command == "repair":
        try:
            task = load_task_spec(arguments.task_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            repair = RepairEngine(config=config).repair(task)
        except (TaskSpecLoadError, RepairError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_repair_result(repair)
        return repair_exit_code(repair)
    elif arguments.command == "benchmark":
        try:
            selected_modes = sum(
                bool(value)
                for value in (
                    arguments.dry_run,
                    arguments.validate_only,
                    arguments.verify_freeze,
                )
            )
            if selected_modes > 1:
                raise BenchmarkError(
                    "choose only one of --dry-run, --validate-only, or --verify-freeze"
                )
            if arguments.write_lock is not None and not arguments.validate_only:
                raise BenchmarkError("--write-lock requires --validate-only")
            suite = load_benchmark_suite(arguments.suite_json)
            config = (
                BumpShieldConfig(state_root=arguments.state_dir)
                if arguments.state_dir is not None
                else BumpShieldConfig()
            )
            runner = BenchmarkRunner(config=config, progress=_benchmark_progress)
            if arguments.verify_freeze:
                frozen = verify_dataset_lock(suite)
                print("BumpShield Final Dataset Freeze")
                print("===============================")
                print(f"Suite: {frozen.suite_id}")
                print(f"Cases: {frozen.case_count}")
                print(f"DIRECT: {frozen.direct_count}")
                print(f"TRANSITIVE: {frozen.transitive_count}")
                print(f"Configuration: {frozen.config_hash}")
                print(f"Dataset: {frozen.dataset_hash}")
                print("Result: VALID")
                return 0
            if arguments.validate_only:
                validation = FinalDatasetService(runner.validator).validate(suite)
                validation_path = (
                    config.state_root / "benchmarks" / f"{suite.id}-validation.json"
                )
                persist_validation(validation_path, validation)
                print("BumpShield Dataset Validation")
                print("=============================")
                for item in validation.cases:
                    status = "VALID" if (
                        item.status.value == "VALID"
                        and item.relationship_valid
                        and item.split_valid
                        and item.provenance_present
                    ) else "INVALID"
                    print(f"- {item.case_id}: {status}")
                print(f"Valid: {sum(1 for item in validation.cases if item.status.value == 'VALID' and item.relationship_valid and item.split_valid and item.provenance_present)}/{len(validation.cases)}")
                print(f"Evidence: {validation_path}")
                if not validation.valid:
                    return 2
                if arguments.write_lock is not None:
                    frozen = write_dataset_lock(
                        arguments.suite_json, arguments.write_lock, validation
                    )
                    print(f"Dataset lock: {arguments.write_lock.resolve()}")
                    print(f"Dataset hash: {frozen.dataset_hash}")
                return 0
            if arguments.dry_run:
                preview = runner.dry_run(suite)
                print("BumpShield Benchmark Dry Run")
                print("============================")
                print(f"Suite: {preview.suite_id}")
                print(f"Cases: {preview.case_count}")
                print("Strategies: " + ", ".join(item.value for item in preview.strategies))
                print(f"Trials: {preview.trials}")
                print(f"Planned case-strategy trials: {preview.planned_trials}")
                print("Provider call budgets:")
                for strategy, budget in preview.provider_call_budgets:
                    print(f"- {strategy.value}: {budget} per trial")
                print(f"Maximum provider calls: {preview.maximum_provider_calls}")
                print("Counterbalanced schedule:")
                current: tuple[str, int] | None = None
                for entry in preview.schedule:
                    key = (entry.case_id, entry.trial)
                    if key != current:
                        print(f"- {entry.case_id} / trial {entry.trial}")
                        current = key
                    print(
                        f"  {entry.execution_position}. {entry.strategy.value}"
                    )
                print("No repair execution performed.")
                return 0
            benchmark = runner.run(
                suite,
                resume_run_id=arguments.resume,
                rerun=arguments.rerun,
            )
            if suite.dataset_lock_path is not None:
                FinalResearchReporter().persist(
                    suite, benchmark, verify_dataset_lock(suite)
                )
        except (BenchmarkLoadError, BenchmarkError, DatasetFreezeError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print_benchmark_result(benchmark)
        return 0
    else:
        parser.print_help()
    return 0


def reproduction_exit_code(status: ReproductionStatus) -> int:
    """Map one reproduction status to the stable CLI exit convention."""
    if status is ReproductionStatus.CONFIRMED:
        return 0
    if status in {ReproductionStatus.BASE_FAILED, ReproductionStatus.UPDATED_PASSED}:
        return 2
    return 1


def print_reproduction(result: ReproductionResult) -> None:
    """Print concise reproduction summary while logs remain in artifacts."""
    updated_status = result.updated.execution.status.value if result.updated else "NOT_RUN"
    print("BumpShield Regression Reproduction")
    print("===================================")
    print(f"Run: {result.run_id}")
    print(f"Repository: {result.task.repository.name}")
    print(f"Base: {result.base.commit} {result.base.execution.status.value}")
    print(f"Updated: {result.task.updated_commit} {updated_status}")
    print(f"Regression: {result.status.value}")
    print(f"Artifacts: {result.artifact_directory}")


def dependency_exit_code(result: DependencyAnalysisResult) -> int:
    """Return success or expectation-mismatch status for completed analysis."""
    return 0 if result.diff.target and result.diff.target.matched else 2


def print_dependency_analysis(result: DependencyAnalysisResult) -> None:
    """Print changed dependencies while complete evidence remains in artifacts."""
    target = result.diff.target
    assert target is not None
    print("BumpShield Dependency Analysis")
    print("==============================")
    print(f"Run: {result.run_id}")
    print(f"Target: {target.group_id}:{target.artifact_id}")
    print(
        f"Expected: {target.expected_base_version} -> "
        f"{target.expected_updated_version}"
    )
    print(
        f"Resolved: {target.resolved_base_version or 'NOT_FOUND'} -> "
        f"{target.resolved_updated_version or 'NOT_FOUND'}"
    )
    print(f"Target matched: {'yes' if target.matched else 'no'}")
    for kind in (
        DependencyChangeKind.UPDATED,
        DependencyChangeKind.ADDED,
        DependencyChangeKind.REMOVED,
    ):
        changes = result.diff.of_kind(kind)
        if changes:
            print(f"\n{kind.value}")
            for change in changes:
                print(_format_dependency_change(change))
    print("\nSummary:")
    for kind in DependencyChangeKind:
        print(f"{kind.value.lower()}: {len(result.diff.of_kind(kind))}")
    print(f"Artifacts: {result.artifact_directory}")


def _format_dependency_change(change: DependencyChange) -> str:
    coordinate = change.after or change.before
    assert coordinate is not None
    label = "TARGET/" if change.is_target else ""
    relationship = f"[{label}{change.relationship.value}]"
    identity = f"{coordinate.group_id}:{coordinate.artifact_id}"
    if change.before and change.after:
        transition = f"{change.before.version} -> {change.after.version}"
        if change.before_scope != change.after_scope:
            transition += f" ({change.before_scope} -> {change.after_scope})"
    elif change.after:
        transition = change.after.version
    else:
        transition = change.before.version
    return f"{relationship} {identity} {transition}"


def failure_exit_code(status: FailureAnalysisStatus) -> int:
    """Map failure-analysis status to stable CLI exit convention."""
    if status is FailureAnalysisStatus.FAILURES_LOCALIZED:
        return 0
    if status in {
        FailureAnalysisStatus.NO_FAILURE,
        FailureAnalysisStatus.FAILURE_UNLOCALIZED,
        FailureAnalysisStatus.FAILURES_PARSED_PARTIALLY,
    }:
        return 2
    return 1


def print_failure_analysis(result: FailureAnalysisResult) -> None:
    """Print primary failure and bounded source context."""
    print("BumpShield Failure Analysis")
    print("===========================")
    print(f"Run: {result.run_id}")
    print(f"Revision: {result.task.updated_commit}")
    print(f"Maven: {result.execution.status.value}")
    print(f"Analysis: {result.status.value}")
    primary = result.primary_failure
    if primary is not None:
        print("\nPrimary Failure")
        print(primary.category.value)
        location = str(primary.file) if primary.file else primary.reported_file or "UNRESOLVED"
        if primary.line is not None:
            location += f":{primary.line}"
            if primary.column is not None:
                location += f":{primary.column}"
        print(location)
        if primary.symbol:
            print(primary.symbol)
        print(primary.message)
        context = next(
            (
                candidate
                for candidate in result.source_contexts
                if candidate.file == primary.file
                and candidate.focus_line == primary.line
            ),
            None,
        )
        if context is not None:
            print("\nSource")
            for line in context.lines:
                marker = ">" if line.number == context.focus_line else " "
                print(f"{marker} {line.number:>4} | {line.text}")
    localized_count = sum(failure.file is not None for failure in result.failures)
    print(f"\nFailures parsed: {len(result.failures)}")
    print(f"Failures localized: {localized_count}")
    print(f"Artifacts: {result.artifact_directory}")


def api_evidence_exit_code(status: ApiAnalysisStatus) -> int:
    """Map useful evidence to success; completed inconclusive analysis to two."""
    return 0 if status is ApiAnalysisStatus.API_EVIDENCE_FOUND else 2


def print_api_evidence(result: ApiEvidenceAnalysisResult) -> None:
    """Print concise primary-failure attribution while raw evidence stays external."""
    print("BumpShield API Evidence")
    print("=======================")
    print(f"Run: {result.run_id}")
    print(f"Result: {result.status.value}")
    primary = result.failure_analysis.primary_failure
    if primary is not None:
        location = str(primary.file) if primary.file else primary.reported_file or "UNRESOLVED"
        if primary.line:
            location += f":{primary.line}"
        print(f"Failure: {primary.category.value} {location}")
        if primary.symbol:
            print(f"Symbol: {primary.symbol}")
    for attribution in result.attributions:
        print(f"Candidate: {attribution.candidate.name}")
        print(f"Ownership: {attribution.ownership.value}")
        for change in attribution.dependencies:
            coordinate = change.after or change.before
            assert coordinate is not None
            versions = (
                f"{change.before.version} -> {change.after.version}"
                if change.before and change.after
                else coordinate.version
            )
            print(
                f"Dependency: {coordinate.group_id}:{coordinate.artifact_id} "
                f"{versions} [{change.relationship.value}]"
            )
        if attribution.dependency_path:
            path = " -> ".join(
                f"{item.group_id}:{item.artifact_id}:{item.version}"
                for item in attribution.dependency_path
            )
            print(f"Path: {path}")
        for evidence in attribution.api_evidence:
            print(f"API evidence: {evidence.kind.value}")
            print(
                "Class presence: "
                f"old={_presence_text(evidence.old_class_present)} "
                f"new={_presence_text(evidence.new_class_present)}"
            )
    if result.issues:
        print(f"Issues: {len(result.issues)}")
    print(f"Artifacts: {result.artifact_directory}")


def _presence_text(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "yes" if value else "no"


def diagnosis_exit_code(status: DiagnosisStatus) -> int:
    """Return zero only for a supported deterministic causal diagnosis."""
    return 0 if status is DiagnosisStatus.SUPPORTED_DIAGNOSIS else 2


def print_diagnosis(diagnosis: CausalDiagnosis) -> None:
    """Print at most three ranked candidates while full evidence stays external."""
    print("BumpShield Causal Diagnosis")
    print("===========================")
    print(f"Run: {diagnosis.run_id}")
    print(f"Diagnosis: {diagnosis.status.value}")
    primary = diagnosis.primary_hypothesis
    if primary is not None:
        print(f"Primary: {primary.summary}")
        print(
            f"Evidence: {primary.evidence_strength.value} "
            f"({primary.evidence_score}/100)"
        )
        print("Causal Chain:")
        for step in primary.causal_chain:
            print(f"{step.order}. {step.description}")
    elif diagnosis.hypotheses:
        print("Candidates:")
        for hypothesis in diagnosis.hypotheses[:3]:
            print(
                f"{hypothesis.rank}. {hypothesis.status.value}: "
                f"{hypothesis.summary}"
            )
    else:
        print(diagnosis.summary)
    print(f"Artifacts: {diagnosis.artifact_directory}")


def plan_exit_code(status: PlanStatus) -> int:
    """Return zero only when bounded automatic planning is ready."""
    return 0 if status is PlanStatus.PLAN_READY else 2


def print_migration_plan(result: MigrationPlanningResult) -> None:
    """Print concise planning output without implying a patch was produced."""
    plan = result.plan
    hypothesis = result.diagnosis.primary_hypothesis
    print("BumpShield Migration Plan")
    print("=========================")
    print(f"Run: {plan.run_id}")
    print(f"Diagnosis: {plan.diagnosis_status.value}")
    if hypothesis is not None:
        print(f"Evidence: {hypothesis.evidence_strength.value}")
    print(f"Migration: {plan.migration_kind.value}")
    print(
        f"Target upgrade: {plan.target_upgrade.group_id}:"
        f"{plan.target_upgrade.artifact_id} {plan.target_upgrade.old_version} -> "
        f"{plan.target_upgrade.new_version}"
    )
    if plan.affected_dependency is not None:
        coordinate = plan.affected_dependency.after or plan.affected_dependency.before
        assert coordinate is not None
        versions = (
            f"{plan.affected_dependency.before.version} -> "
            f"{plan.affected_dependency.after.version}"
            if plan.affected_dependency.before and plan.affected_dependency.after
            else coordinate.version
        )
        print(
            f"Dependency: {coordinate.group_id}:{coordinate.artifact_id} "
            f"{versions} [{plan.affected_dependency.relationship.value}]"
        )
    if plan.affected_class:
        print(f"Affected class: {plan.affected_class}")
    if plan.affected_member:
        print(f"Affected member: {plan.affected_member}")
    if plan.primary_source_location:
        location = plan.primary_source_location
        print(f"Primary location: {location.file}:{location.line}")
    related = tuple(
        location
        for location in plan.affected_source_locations
        if location.kind is not AffectedLocationKind.PRIMARY_FAILURE
    )
    if related:
        print("Related locations:")
        for location in related:
            print(f"- {location.file}:{location.line} [{location.kind.value}]")
    if plan.new_api_candidates:
        print("New API candidates (not verified replacements):")
        for candidate in plan.new_api_candidates:
            print(f"- {candidate.rank}. {candidate.member.declaration}")
    if plan.missing_parameter_types:
        print(
            "New required parameter types: "
            + ", ".join(plan.missing_parameter_types)
        )
        print("Argument values: not selected by deterministic planning")
    print(f"Required outcome: {plan.required_outcome}")
    if plan.allowed_files:
        print("Initial allowed files:")
        for path in plan.allowed_files:
            print(f"- {path}")
    print("Repair constraints:")
    for constraint in plan.constraints:
        print(f"- {constraint.value}")
    if plan.verification_commands:
        print("Future verification:")
        for command in plan.verification_commands:
            print("- " + " ".join(command.command))
    print(f"Scope: {plan.scope.value}")
    print(f"Plan status: {plan.status.value}")
    print(f"Artifacts: {plan.artifact_directory}")


def repair_exit_code(result: RepairResult) -> int:
    """Map verified, completed-unresolved, and provider infrastructure outcomes."""
    if result.status is MigrationStatus.VERIFIED_MIGRATION:
        return 0
    if result.attempts:
        provider = result.attempts[-1].provider_result
        if provider is not None and provider.status in {
            RepairProviderStatus.UNAVAILABLE,
            RepairProviderStatus.ERROR,
        }:
            return 1
    return 2


def _benchmark_progress(position, total, case, strategy, status) -> None:
    """Print one compact durable progress row per completed trial."""
    print(f"[{position}/{total}] {case.id} / {strategy.value}: {status}")


def print_benchmark_result(result: BenchmarkRunResult) -> None:
    """Print aggregate VRR while detailed evidence remains external."""
    print("BumpShield Benchmark")
    print("====================")
    print(f"Suite: {result.suite_id}")
    print(f"Run: {result.benchmark_run_id}")
    print(f"Cases: {result.summary.total_cases}")
    print(f"Run status: {result.status.value}")
    print(
        f"Trials: {result.completed_trials}/{result.planned_trials} completed, "
        f"{result.unexecuted_trials} unexecuted"
    )
    print("\nSummary")
    print("Strategy | Verified | Attempted | Strict VRR | Provider-available VRR")
    for metric in result.summary.overall:
        rate = (
            "n/a" if metric.strict_vrr is None else f"{metric.strict_vrr * 100:.1f}%"
        )
        conditional = (
            "n/a"
            if metric.provider_available_vrr is None
            else f"{metric.provider_available_vrr * 100:.1f}%"
        )
        print(
            f"{metric.strategy.value} | {metric.verified} | "
            f"{metric.attempted_valid} | {rate} | {conditional}"
        )
    print(f"Results: {result.artifact_directory}")


def print_repair_result(result: RepairResult) -> None:
    """Print objective repair attempts while full logs stay in artifacts."""
    print("BumpShield Repair")
    print("=================")
    print(f"Run: {result.run_id}")
    for attempt in result.attempts:
        print(f"Attempt {attempt.attempt_number}: {attempt.status.value}")
        print(
            f"Patch: {len(attempt.modified_files)} files, "
            f"+{attempt.lines_added} -{attempt.lines_removed}"
        )
        print(
            "Compile: "
            + (
                attempt.compile_result.status.value
                if attempt.compile_result is not None
                else "NOT_RUN"
            )
        )
        print(
            "Tests: "
            + (
                attempt.test_result.status.value
                if attempt.test_result is not None
                else "NOT_RUN"
            )
        )
    if result.verification is not None:
        print("Independent Verification:")
        for check in result.verification.checks:
            print(f"- {check.name}: {check.status.value}")
    print(f"FINAL STATUS: {result.status.value}")
    if result.winning_attempt is not None:
        print(f"Patch: {result.artifact_directory / 'final.patch'}")
    print(f"Artifacts: {result.artifact_directory}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
