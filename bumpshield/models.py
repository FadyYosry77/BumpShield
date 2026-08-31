"""Typed data exchanged between BumpShield components."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class ExecutionStatus(StrEnum):
    """Outcome of a build, test, or other bounded execution."""

    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


class MigrationStatus(StrEnum):
    """Final status of a migration task."""

    VERIFIED_MIGRATION = "VERIFIED_MIGRATION"
    UNRESOLVED = "UNRESOLVED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    INVALID_CASE = "INVALID_CASE"


class ReproductionStatus(StrEnum):
    """Classification of base and updated revision execution."""

    CONFIRMED = "CONFIRMED"
    BASE_FAILED = "BASE_FAILED"
    UPDATED_PASSED = "UPDATED_PASSED"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class FailureCategory(StrEnum):
    """Deterministically recognized Java build or test failure kind."""

    MISSING_SYMBOL = "MISSING_SYMBOL"
    METHOD_ARGUMENT_MISMATCH = "METHOD_ARGUMENT_MISMATCH"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    INCOMPATIBLE_TYPES = "INCOMPATIBLE_TYPES"
    TEST_FAILURE = "TEST_FAILURE"
    ASSERTION_FAILURE = "ASSERTION_FAILURE"
    TEST_EXCEPTION = "TEST_EXCEPTION"
    COMPILATION_ERROR_OTHER = "COMPILATION_ERROR_OTHER"


class FailureAnalysisStatus(StrEnum):
    """Outcome of deterministic failure parsing and localization."""

    FAILURES_LOCALIZED = "FAILURES_LOCALIZED"
    FAILURES_PARSED_PARTIALLY = "FAILURES_PARSED_PARTIALLY"
    FAILURE_UNLOCALIZED = "FAILURE_UNLOCALIZED"
    NO_FAILURE = "NO_FAILURE"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"


class TypeCandidateOrigin(StrEnum):
    """Deterministic source of one candidate Java type."""

    COMPILER_TYPE = "COMPILER_TYPE"
    EXPLICIT_IMPORT = "EXPLICIT_IMPORT"
    STATIC_IMPORT = "STATIC_IMPORT"
    WILDCARD_IMPORT = "WILDCARD_IMPORT"
    STACK_FRAME = "STACK_FRAME"
    PACKAGE_REFERENCE = "PACKAGE_REFERENCE"


class ClassOwnershipStatus(StrEnum):
    """Outcome of matching one type against changed dependency artifacts."""

    EXACT_SINGLE_MATCH = "EXACT_SINGLE_MATCH"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
    NO_MATCH = "NO_MATCH"
    PROJECT_OWNED = "PROJECT_OWNED"


class ApiMemberKind(StrEnum):
    """Supported public member kinds parsed from ``javap``."""

    METHOD = "METHOD"
    CONSTRUCTOR = "CONSTRUCTOR"
    FIELD = "FIELD"


class ApiEvidenceKind(StrEnum):
    """Observed old-versus-new API fact relevant to a failure."""

    CLASS_PRESENT_BOTH = "CLASS_PRESENT_BOTH"
    REMOVED_CLASS = "REMOVED_CLASS"
    ADDED_CLASS = "ADDED_CLASS"
    REMOVED_MEMBER = "REMOVED_MEMBER"
    ADDED_MEMBER = "ADDED_MEMBER"
    CHANGED_MEMBER_SIGNATURE = "CHANGED_MEMBER_SIGNATURE"
    RELEVANT_MEMBER_UNCHANGED = "RELEVANT_MEMBER_UNCHANGED"
    DEPENDENCY_REMOVED_WITH_CLASS = "DEPENDENCY_REMOVED_WITH_CLASS"
    PACKAGE_REMOVED = "PACKAGE_REMOVED"
    NO_RELEVANT_API_CHANGE = "NO_RELEVANT_API_CHANGE"
    API_INSPECTION_UNAVAILABLE = "API_INSPECTION_UNAVAILABLE"


class ApiMatchStrategy(StrEnum):
    """Precision used to relate a compiler symbol to an API member."""

    EXACT_PARAMETERS = "EXACT_PARAMETERS"
    NAME_ONLY = "NAME_ONLY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ApiAnalysisStatus(StrEnum):
    """Overall outcome of targeted Phase 4 evidence collection."""

    API_EVIDENCE_FOUND = "API_EVIDENCE_FOUND"
    CLASS_ATTRIBUTED_NO_API_CHANGE = "CLASS_ATTRIBUTED_NO_API_CHANGE"
    AMBIGUOUS_ATTRIBUTION = "AMBIGUOUS_ATTRIBUTION"
    NO_CHANGED_DEPENDENCY_ATTRIBUTION = "NO_CHANGED_DEPENDENCY_ATTRIBUTION"
    PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"
    API_TOOL_UNAVAILABLE = "API_TOOL_UNAVAILABLE"
    NO_SUPPORTED_FAILURE = "NO_SUPPORTED_FAILURE"


class HypothesisStatus(StrEnum):
    """Deterministic support state for one causal hypothesis."""

    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    CONTRADICTED = "CONTRADICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceStrength(StrEnum):
    """Qualitative completeness of a deterministic evidence chain."""

    VERY_STRONG = "VERY_STRONG"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INSUFFICIENT = "INSUFFICIENT"


class CausalStepKind(StrEnum):
    """Supported transition in an evidence-backed causal chain."""

    TARGET_UPGRADE = "TARGET_UPGRADE"
    DEPENDENCY_RESOLUTION_CHANGE = "DEPENDENCY_RESOLUTION_CHANGE"
    API_CHANGE = "API_CHANGE"
    PROJECT_USAGE = "PROJECT_USAGE"
    OBSERVED_FAILURE = "OBSERVED_FAILURE"


class CausalHypothesisKind(StrEnum):
    """Concrete local change proposed as an explanation of the failure."""

    REMOVED_MEMBER = "REMOVED_MEMBER"
    CHANGED_MEMBER_SIGNATURE = "CHANGED_MEMBER_SIGNATURE"
    REMOVED_CLASS = "REMOVED_CLASS"
    REMOVED_PACKAGE = "REMOVED_PACKAGE"
    REMOVED_DEPENDENCY = "REMOVED_DEPENDENCY"
    AMBIGUOUS_OWNERSHIP = "AMBIGUOUS_OWNERSHIP"
    API_INSPECTION_UNAVAILABLE = "API_INSPECTION_UNAVAILABLE"
    RELEVANT_MEMBER_UNCHANGED = "RELEVANT_MEMBER_UNCHANGED"


class EvidenceReferenceKind(StrEnum):
    """Auditable deterministic fact referenced by a hypothesis."""

    DEPENDENCY_UPDATE = "DEPENDENCY_UPDATE"
    EXACT_CLASS_OWNERSHIP = "EXACT_CLASS_OWNERSHIP"
    AMBIGUOUS_CLASS_OWNERSHIP = "AMBIGUOUS_CLASS_OWNERSHIP"
    API_CHANGE = "API_CHANGE"
    FAILURE_SYMBOL_MATCH = "FAILURE_SYMBOL_MATCH"
    SOURCE_LOCALIZED = "SOURCE_LOCALIZED"
    SOURCE_CALL_SITE = "SOURCE_CALL_SITE"
    TARGET_DEPENDENCY_PATH = "TARGET_DEPENDENCY_PATH"
    API_INSPECTION_UNAVAILABLE = "API_INSPECTION_UNAVAILABLE"
    DEPENDENCY_PATH_INCOMPLETE = "DEPENDENCY_PATH_INCOMPLETE"
    SOURCE_UNRESOLVED = "SOURCE_UNRESOLVED"
    RELEVANT_MEMBER_UNCHANGED = "RELEVANT_MEMBER_UNCHANGED"
    EVIDENCE_INCONSISTENCY = "EVIDENCE_INCONSISTENCY"


class DiagnosisStatus(StrEnum):
    """Overall deterministic causal-diagnosis outcome."""

    SUPPORTED_DIAGNOSIS = "SUPPORTED_DIAGNOSIS"
    AMBIGUOUS_DIAGNOSIS = "AMBIGUOUS_DIAGNOSIS"
    PARTIAL_DIAGNOSIS = "PARTIAL_DIAGNOSIS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class PlanStatus(StrEnum):
    """Outcome of deterministic migration planning."""

    PLAN_READY = "PLAN_READY"
    PLAN_PARTIAL = "PLAN_PARTIAL"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    NO_ACTIONABLE_DIAGNOSIS = "NO_ACTIONABLE_DIAGNOSIS"


class MigrationKind(StrEnum):
    """Supported shape of project migration work."""

    REMOVED_METHOD = "REMOVED_METHOD"
    CHANGED_METHOD_SIGNATURE = "CHANGED_METHOD_SIGNATURE"
    REMOVED_CLASS = "REMOVED_CLASS"
    REMOVED_PACKAGE = "REMOVED_PACKAGE"
    REMOVED_DEPENDENCY = "REMOVED_DEPENDENCY"
    TYPE_COMPATIBILITY = "TYPE_COMPATIBILITY"
    UNKNOWN = "UNKNOWN"


class AffectedLocationKind(StrEnum):
    """Deterministic relationship of one source location to the migration."""

    PRIMARY_FAILURE = "PRIMARY_FAILURE"
    EXACT_IMPORT = "EXACT_IMPORT"
    POTENTIAL_CALL_SITE = "POTENTIAL_CALL_SITE"
    POTENTIAL_TYPE_REFERENCE = "POTENTIAL_TYPE_REFERENCE"


class SourceFileKind(StrEnum):
    """Editable role of one Java source file."""

    PRODUCTION_SOURCE = "PRODUCTION_SOURCE"
    TEST_SOURCE = "TEST_SOURCE"
    GENERATED_SOURCE = "GENERATED_SOURCE"


class MigrationCandidateKind(StrEnum):
    """Non-semantic relationship of one new API member to old usage."""

    SAME_NAME_NEW_SIGNATURE = "SAME_NAME_NEW_SIGNATURE"
    RELATED_SAME_CLASS_MEMBER = "RELATED_SAME_CLASS_MEMBER"
    RELATED_OVERLOAD = "RELATED_OVERLOAD"


class CandidateMatchReason(StrEnum):
    """Deterministic lexical/type signal used to order API candidates."""

    SAME_DECLARING_CLASS = "SAME_DECLARING_CLASS"
    SAME_MEMBER_NAME = "SAME_MEMBER_NAME"
    SHARED_NAME_PREFIX = "SHARED_NAME_PREFIX"
    SAME_RETURN_TYPE = "SAME_RETURN_TYPE"
    OVERLAPPING_PARAMETER_TYPES = "OVERLAPPING_PARAMETER_TYPES"


class RepairConstraint(StrEnum):
    """Guardrail future repair must preserve."""

    TARGET_VERSION_MUST_REMAIN = "TARGET_VERSION_MUST_REMAIN"
    TARGET_DEPENDENCY_MUST_REMAIN = "TARGET_DEPENDENCY_MUST_REMAIN"
    CAUSAL_DEPENDENCY_NO_DOWNGRADE = "CAUSAL_DEPENDENCY_NO_DOWNGRADE"
    NO_TEST_DELETION = "NO_TEST_DELETION"
    NO_TEST_DISABLEMENT = "NO_TEST_DISABLEMENT"
    NO_TEST_SKIP_CONFIGURATION = "NO_TEST_SKIP_CONFIGURATION"
    NO_FUNCTIONALITY_REMOVAL = "NO_FUNCTIONALITY_REMOVAL"
    NO_DUMMY_IMPLEMENTATION = "NO_DUMMY_IMPLEMENTATION"
    NO_COMPILER_ERROR_SUPPRESSION = "NO_COMPILER_ERROR_SUPPRESSION"
    MINIMAL_PATCH = "MINIMAL_PATCH"
    NO_UNRELATED_CHANGES = "NO_UNRELATED_CHANGES"
    ADDITIONAL_FILES_REQUIRE_JUSTIFICATION = (
        "ADDITIONAL_FILES_REQUIRE_JUSTIFICATION"
    )


class VerificationRequirement(StrEnum):
    """Objective check required after future repair execution."""

    TARGET_VERSION_RETAINED = "TARGET_VERSION_RETAINED"
    TARGET_DEPENDENCY_PRESENT = "TARGET_DEPENDENCY_PRESENT"
    COMPILE_PASSES = "COMPILE_PASSES"
    TESTS_PASS = "TESTS_PASS"
    TESTS_RETAINED = "TESTS_RETAINED"
    TESTS_ENABLED = "TESTS_ENABLED"
    PATCH_SCOPE_ACCEPTABLE = "PATCH_SCOPE_ACCEPTABLE"


class VerificationCommandKind(StrEnum):
    """Role of a future Maven verification command."""

    FAST_CHECK = "FAST_CHECK"
    FINAL_CHECK = "FINAL_CHECK"


class PlanScope(StrEnum):
    """Affected-file count band, not repair difficulty or probability."""

    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class RepairProviderStatus(StrEnum):
    """Outcome of one bounded repair-provider invocation."""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"


class RepairAttemptStatus(StrEnum):
    """Deterministic lifecycle state of one repair attempt."""

    PATCH_CREATED = "PATCH_CREATED"
    NO_CHANGES = "NO_CHANGES"
    PATCH_REJECTED = "PATCH_REJECTED"
    COMPILE_FAILED = "COMPILE_FAILED"
    TEST_FAILED = "TEST_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFIED = "VERIFIED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TIMEOUT = "TIMEOUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class PatchScopeStatus(StrEnum):
    """Relationship between actual patch and Phase 6 source evidence."""

    IN_SCOPE = "IN_SCOPE"
    JUSTIFIED_EXPANSION = "JUSTIFIED_EXPANSION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class VerificationCheckStatus(StrEnum):
    """Result of one independent deterministic verification check."""

    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"


class VerificationStatus(StrEnum):
    """Overall result of independent verification."""

    VERIFIED_MIGRATION = "VERIFIED_MIGRATION"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class DependencyChangeKind(StrEnum):
    """How one resolved dependency changed between revisions."""

    ADDED = "ADDED"
    REMOVED = "REMOVED"
    UPDATED = "UPDATED"
    UNCHANGED = "UNCHANGED"


class DependencyRelationship(StrEnum):
    """Relationship of a dependency to the analyzed project."""

    DIRECT = "DIRECT"
    TRANSITIVE = "TRANSITIVE"


class WorkspaceKind(StrEnum):
    """Role of an isolated repository workspace."""

    BASE = "BASE"
    UPDATED = "UPDATED"
    REPAIR = "REPAIR"


def _require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True, slots=True)
class DependencyKey:
    """Version-independent Maven dependency identity."""

    group_id: str
    artifact_id: str
    type: str = "jar"
    classifier: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.group_id, "group_id")
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.type, "type")
        if self.classifier is not None:
            _require_text(self.classifier, "classifier")


@dataclass(frozen=True, slots=True)
class DependencyCoordinate:
    """A resolved Maven dependency coordinate."""

    group_id: str
    artifact_id: str
    version: str
    type: str = "jar"
    classifier: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.group_id, "group_id")
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.version, "version")
        _require_text(self.type, "type")
        if self.classifier is not None:
            _require_text(self.classifier, "classifier")

    @property
    def key(self) -> DependencyKey:
        """Return identity without the resolved version."""
        return DependencyKey(
            group_id=self.group_id,
            artifact_id=self.artifact_id,
            type=self.type,
            classifier=self.classifier,
        )


@dataclass(frozen=True, slots=True)
class DependencyUpgrade:
    """Requested version transition for one Maven dependency."""

    group_id: str
    artifact_id: str
    old_version: str
    new_version: str

    def __post_init__(self) -> None:
        _require_text(self.group_id, "group_id")
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.old_version, "old_version")
        _require_text(self.new_version, "new_version")


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Input identifying a known dependency-upgrade regression."""

    repository: Path
    base_commit: str
    updated_commit: str
    target_dependency: DependencyUpgrade

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", Path(self.repository))
        _require_text(self.base_commit, "base_commit")
        _require_text(self.updated_commit, "updated_commit")


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured result of one external command."""

    command: tuple[str, ...]
    cwd: Path
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Combined outcome of one logical build or test execution."""

    status: ExecutionStatus
    commands: tuple[CommandResult, ...] = ()
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RevisionExecution:
    """Execution result tied to one requested Git revision."""

    commit: str
    execution: ExecutionResult

    def __post_init__(self) -> None:
        _require_text(self.commit, "commit")


@dataclass(frozen=True, slots=True)
class ReproductionResult:
    """Structured result of deterministic regression reproduction."""

    run_id: str
    status: ReproductionStatus
    task: TaskSpec
    artifact_directory: Path
    base: RevisionExecution
    updated: RevisionExecution | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))


@dataclass(frozen=True, slots=True)
class DependencyNode:
    """One dependency in a resolved Maven dependency graph."""

    coordinate: DependencyCoordinate
    relationship: DependencyRelationship
    scope: str | None = None
    depth: int = 1
    parent: DependencyKey | None = None
    children: tuple[DependencyNode, ...] = ()

    def __post_init__(self) -> None:
        if self.depth < 1:
            raise ValueError("dependency depth must be at least 1")
        if self.scope is not None:
            _require_text(self.scope, "scope")

    @property
    def key(self) -> DependencyKey:
        """Return this node's version-independent identity."""
        return self.coordinate.key


@dataclass(frozen=True, slots=True)
class DependencyChange:
    """One classified resolved-dependency comparison."""

    kind: DependencyChangeKind
    relationship: DependencyRelationship
    before: DependencyCoordinate | None = None
    after: DependencyCoordinate | None = None
    before_scope: str | None = None
    after_scope: str | None = None
    is_target: bool = False

    def __post_init__(self) -> None:
        if self.kind is DependencyChangeKind.ADDED and (
            self.before is not None or self.after is None
        ):
            raise ValueError("ADDED changes require only an after coordinate")
        if self.kind is DependencyChangeKind.REMOVED and (
            self.before is None or self.after is not None
        ):
            raise ValueError("REMOVED changes require only a before coordinate")
        if self.kind is DependencyChangeKind.UPDATED and (
            self.before is None or self.after is None
        ):
            raise ValueError("UPDATED changes require before and after coordinates")
        if self.kind is DependencyChangeKind.UNCHANGED and (
            self.before is None or self.after is None
        ):
            raise ValueError("UNCHANGED changes require before and after coordinates")


@dataclass(frozen=True, slots=True)
class TargetDependencyResolution:
    """Expected and observed versions of the requested dependency transition."""

    group_id: str
    artifact_id: str
    expected_base_version: str
    resolved_base_version: str | None
    expected_updated_version: str
    resolved_updated_version: str | None

    def __post_init__(self) -> None:
        _require_text(self.group_id, "group_id")
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.expected_base_version, "expected_base_version")
        _require_text(self.expected_updated_version, "expected_updated_version")
        if self.resolved_base_version is not None:
            _require_text(self.resolved_base_version, "resolved_base_version")
        if self.resolved_updated_version is not None:
            _require_text(self.resolved_updated_version, "resolved_updated_version")

    @property
    def matched(self) -> bool:
        """Return whether both revisions resolved the requested versions."""
        return (
            self.resolved_base_version == self.expected_base_version
            and self.resolved_updated_version == self.expected_updated_version
        )


@dataclass(frozen=True, slots=True)
class DependencyDiff:
    """Complete set of dependency changes between two revisions."""

    changes: tuple[DependencyChange, ...] = ()
    target: TargetDependencyResolution | None = None

    def of_kind(self, kind: DependencyChangeKind) -> tuple[DependencyChange, ...]:
        """Return changes of one classification."""
        return tuple(change for change in self.changes if change.kind is kind)

    @property
    def transitive_updates(self) -> tuple[DependencyChange, ...]:
        """Return updated transitive dependencies for later causal analysis."""
        return tuple(
            change
            for change in self.changes
            if change.kind is DependencyChangeKind.UPDATED
            and change.relationship is DependencyRelationship.TRANSITIVE
        )


@dataclass(frozen=True, slots=True)
class DependencyTreeCommandResult:
    """Raw output and process result from one Maven dependency-tree command."""

    execution: ExecutionResult
    output_file: Path
    raw_output: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_file", Path(self.output_file))


@dataclass(frozen=True, slots=True)
class ResolvedArtifactsCommandResult:
    """Raw Maven ``dependency:list`` evidence for one revision."""

    execution: ExecutionResult
    output_file: Path
    raw_output: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_file", Path(self.output_file))


@dataclass(frozen=True, slots=True)
class JavaApiCommandResult:
    """One bounded ``javap`` inspection result."""

    execution: ExecutionResult
    artifact: Path
    class_name: str
    raw_output: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact", Path(self.artifact))
        _require_text(self.class_name, "class_name")


@dataclass(frozen=True, slots=True)
class DependencyTreeResult:
    """Parsed resolved dependencies for one revision."""

    commit: str
    execution: ExecutionResult
    nodes: tuple[DependencyNode, ...]
    raw_output_path: Path
    parse_warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.commit, "commit")
        object.__setattr__(self, "raw_output_path", Path(self.raw_output_path))


@dataclass(frozen=True, slots=True)
class DependencyAnalysisResult:
    """Structured output of base-versus-updated dependency comparison."""

    run_id: str
    task: TaskSpec
    artifact_directory: Path
    base: DependencyTreeResult
    updated: DependencyTreeResult
    diff: DependencyDiff

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))


@dataclass(frozen=True, slots=True)
class StackFrame:
    """One source-bearing Java stack frame captured from test output."""

    class_name: str
    method_name: str
    file_name: str
    line: int

    def __post_init__(self) -> None:
        _require_text(self.class_name, "class_name")
        _require_text(self.method_name, "method_name")
        _require_text(self.file_name, "file_name")
        if self.line < 1:
            raise ValueError("stack frame line must be at least 1")


@dataclass(frozen=True, slots=True)
class FailureSignal:
    """Structured compiler or test failure evidence."""

    category: FailureCategory
    message: str
    file: Path | None = None
    line: int | None = None
    column: int | None = None
    symbol: str | None = None
    location: str | None = None
    required: str | None = None
    found: str | None = None
    test_class: str | None = None
    test_method: str | None = None
    exception_type: str | None = None
    reported_file: str | None = None
    stack_frames: tuple[StackFrame, ...] = ()
    raw_excerpt: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.message, "message")
        if self.file is not None:
            object.__setattr__(self, "file", Path(self.file))
        if self.line is not None and self.line < 1:
            raise ValueError("failure line must be at least 1")
        if self.column is not None and self.column < 1:
            raise ValueError("failure column must be at least 1")


@dataclass(frozen=True, slots=True)
class SourceLine:
    """One one-based source line retained in localized context."""

    number: int
    text: str

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("source line number must be at least 1")


@dataclass(frozen=True, slots=True)
class SourceContext:
    """Small repository-relative Java source window around one failure."""

    file: Path
    start_line: int
    end_line: int
    focus_line: int
    lines: tuple[SourceLine, ...]
    package: str | None = None
    imports: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "file", Path(self.file))
        if self.file.is_absolute() or ".." in self.file.parts:
            raise ValueError("source context file must be repository-relative")
        if not 1 <= self.start_line <= self.focus_line <= self.end_line:
            raise ValueError("source context line range is invalid")


@dataclass(frozen=True, slots=True)
class FailureAnalysisResult:
    """Structured updated-revision failure analysis."""

    run_id: str
    task: TaskSpec
    artifact_directory: Path
    status: FailureAnalysisStatus
    execution: ExecutionResult
    failures: tuple[FailureSignal, ...] = ()
    source_contexts: tuple[SourceContext, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))

    @property
    def primary_failure(self) -> FailureSignal | None:
        """Select first localized compiler, localized test, then first signal."""
        compiler_categories = {
            FailureCategory.MISSING_SYMBOL,
            FailureCategory.METHOD_ARGUMENT_MISMATCH,
            FailureCategory.PACKAGE_NOT_FOUND,
            FailureCategory.INCOMPATIBLE_TYPES,
            FailureCategory.COMPILATION_ERROR_OTHER,
        }
        test_categories = {
            FailureCategory.TEST_FAILURE,
            FailureCategory.ASSERTION_FAILURE,
            FailureCategory.TEST_EXCEPTION,
        }
        for categories in (compiler_categories, test_categories):
            for failure in self.failures:
                if failure.file is not None and failure.category in categories:
                    return failure
        return self.failures[0] if self.failures else None


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    """One Maven dependency resolved to a physical artifact file."""

    coordinate: DependencyCoordinate
    scope: str
    path: Path

    def __post_init__(self) -> None:
        _require_text(self.scope, "scope")
        object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True, slots=True)
class TypeCandidate:
    """Java class or package deterministically derived from failure evidence."""

    name: str
    origin: TypeCandidateOrigin
    project_owned: bool = False
    is_package: bool = False

    def __post_init__(self) -> None:
        _require_text(self.name, "name")


@dataclass(frozen=True, slots=True)
class ApiMember:
    """Small normalized representation of one public ``javap`` declaration."""

    kind: ApiMemberKind
    name: str
    declaration: str
    parameter_types: tuple[str, ...] = ()
    return_type: str | None = None
    is_static: bool = False

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        _require_text(self.declaration, "declaration")


@dataclass(frozen=True, slots=True)
class ApiEvidence:
    """Auditable API comparison for one class and changed dependency."""

    kind: ApiEvidenceKind
    class_name: str
    failure_symbol: str | None
    before: DependencyCoordinate | None
    after: DependencyCoordinate | None
    old_class_present: bool | None
    new_class_present: bool | None
    old_members: tuple[ApiMember, ...] = ()
    new_members: tuple[ApiMember, ...] = ()
    old_class_members: tuple[ApiMember, ...] = ()
    new_class_members: tuple[ApiMember, ...] = ()
    match_strategy: ApiMatchStrategy = ApiMatchStrategy.NOT_APPLICABLE

    def __post_init__(self) -> None:
        _require_text(self.class_name, "class_name")


@dataclass(frozen=True, slots=True)
class DependencyAttribution:
    """Class ownership and graph provenance for changed dependencies."""

    candidate: TypeCandidate
    ownership: ClassOwnershipStatus
    dependencies: tuple[DependencyChange, ...] = ()
    dependency_path: tuple[DependencyCoordinate, ...] = ()
    target_on_path: bool = False
    api_evidence: tuple[ApiEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ApiEvidenceAnalysisResult:
    """Structured Phase 4 result composed from dependency and failure evidence."""

    run_id: str
    task: TaskSpec
    artifact_directory: Path
    status: ApiAnalysisStatus
    dependency_analysis: DependencyAnalysisResult
    failure_analysis: FailureAnalysisResult
    candidates: tuple[TypeCandidate, ...] = ()
    base_artifacts: tuple[ResolvedArtifact, ...] = ()
    updated_artifacts: tuple[ResolvedArtifact, ...] = ()
    attributions: tuple[DependencyAttribution, ...] = ()
    issues: tuple[str, ...] = ()
    evidence_bundle: EvidenceBundle | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Targeted evidence supplied to causal investigation."""

    target_upgrade: DependencyUpgrade
    run_id: str | None = None
    task: TaskSpec | None = None
    artifact_directory: Path | None = None
    base_execution: ExecutionResult | None = None
    updated_execution: ExecutionResult | None = None
    dependency_diff: DependencyDiff = field(default_factory=DependencyDiff)
    failures: tuple[FailureSignal, ...] = ()
    source_contexts: tuple[SourceContext, ...] = ()
    dependency_attributions: tuple[DependencyAttribution, ...] = ()
    api_evidence: tuple[ApiEvidence, ...] = ()
    issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.run_id is not None:
            _require_text(self.run_id, "run_id")
        if self.artifact_directory is not None:
            object.__setattr__(
                self, "artifact_directory", Path(self.artifact_directory)
            )

    @property
    def primary_failure(self) -> FailureSignal | None:
        """Return the primary failure selected by the Phase 4 bundle."""
        return self.failures[0] if self.failures else None


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """Stable reference to one persisted or structured evidence fact."""

    id: str
    kind: EvidenceReferenceKind
    detail: str
    artifact: str

    def __post_init__(self) -> None:
        _require_text(self.id, "evidence reference id")
        _require_text(self.detail, "evidence reference detail")
        _require_text(self.artifact, "evidence reference artifact")


@dataclass(frozen=True, slots=True)
class CausalStep:
    """One ordered transition supported by explicit evidence references."""

    order: int
    kind: CausalStepKind
    description: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.order < 1:
            raise ValueError("causal step order must be at least 1")
        _require_text(self.description, "causal step description")


@dataclass(frozen=True, slots=True)
class RootCauseHypothesis:
    """Concrete suspected cause and evidence-backed causal chain."""

    id: str
    rank: int
    status: HypothesisStatus
    kind: CausalHypothesisKind
    summary: str
    implicated_dependencies: tuple[DependencyChange, ...]
    dependency_path: tuple[DependencyCoordinate, ...]
    target_on_path: bool
    failure: FailureSignal | None
    causal_chain: tuple[CausalStep, ...]
    supporting_evidence: tuple[EvidenceReference, ...]
    contradictory_evidence: tuple[EvidenceReference, ...]
    missing_evidence: tuple[EvidenceReference, ...]
    evidence_strength: EvidenceStrength
    evidence_score: int
    explanation: str

    def __post_init__(self) -> None:
        _require_text(self.id, "hypothesis id")
        _require_text(self.summary, "hypothesis summary")
        _require_text(self.explanation, "hypothesis explanation")
        if self.rank < 0:
            raise ValueError("hypothesis rank must not be negative")
        if not 0 <= self.evidence_score <= 100:
            raise ValueError("evidence score must be between 0 and 100")
        expected_orders = tuple(range(1, len(self.causal_chain) + 1))
        if tuple(step.order for step in self.causal_chain) != expected_orders:
            raise ValueError("causal steps must use contiguous one-based order")

    @property
    def root_cause(self) -> str:
        """Compatibility alias for the structured hypothesis summary."""
        return self.summary


@dataclass(frozen=True, slots=True)
class CausalDiagnosis:
    """Ordered deterministic hypotheses derived from one Phase 4 bundle."""

    run_id: str
    status: DiagnosisStatus
    artifact_directory: Path
    hypotheses: tuple[RootCauseHypothesis, ...]
    summary: str
    unresolved_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.summary, "diagnosis summary")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))

    @property
    def primary_hypothesis(self) -> RootCauseHypothesis | None:
        """Return a meaningful unique lead, never an invented insufficient one."""
        if self.status in {
            DiagnosisStatus.AMBIGUOUS_DIAGNOSIS,
            DiagnosisStatus.INSUFFICIENT_EVIDENCE,
        }:
            return None
        return self.hypotheses[0] if self.hypotheses else None


@dataclass(frozen=True, slots=True)
class DiagnosisRun:
    """Phase 5 diagnosis paired with the Phase 4 evidence it consumed."""

    task: TaskSpec
    evidence: EvidenceBundle
    diagnosis: CausalDiagnosis


@dataclass(frozen=True, slots=True)
class AffectedSourceLocation:
    """One safely bounded Java source usage relevant to migration planning."""

    file: Path
    line: int
    kind: AffectedLocationKind
    source_kind: SourceFileKind
    evidence_strength: EvidenceStrength
    excerpt: str

    def __post_init__(self) -> None:
        path = Path(self.file)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("affected source file must be repository-relative")
        if path.suffix != ".java":
            raise ValueError("affected source file must be Java source")
        if self.line < 1:
            raise ValueError("affected source line must be at least 1")
        _require_text(self.excerpt, "affected source excerpt")
        object.__setattr__(self, "file", path)


@dataclass(frozen=True, slots=True)
class MigrationCandidate:
    """Ranked new API candidate, never a verified semantic replacement."""

    rank: int
    class_name: str
    member: ApiMember
    kind: MigrationCandidateKind
    match_reasons: tuple[CandidateMatchReason, ...]
    evidence_strength: EvidenceStrength
    verified_replacement: bool = False

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("migration candidate rank must be at least 1")
        _require_text(self.class_name, "migration candidate class")
        if self.verified_replacement:
            raise ValueError("Phase 6 candidates cannot be verified replacements")


@dataclass(frozen=True, slots=True)
class VerificationCommand:
    """Future command required for fast or final repair verification."""

    kind: VerificationCommandKind
    command: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.command or any(not part.strip() for part in self.command):
            raise ValueError("verification command must contain non-empty arguments")


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """Bounded deterministic work specification for a future repair agent."""

    plan_id: str
    run_id: str
    artifact_directory: Path
    status: PlanStatus
    diagnosis_status: DiagnosisStatus
    hypothesis_id: str | None
    migration_kind: MigrationKind
    summary: str
    target_upgrade: DependencyUpgrade
    affected_dependency: DependencyChange | None
    affected_class: str | None
    affected_member: str | None
    old_api: tuple[ApiMember, ...]
    new_api_candidates: tuple[MigrationCandidate, ...]
    missing_parameter_types: tuple[str, ...]
    primary_source_location: AffectedSourceLocation | None
    affected_source_locations: tuple[AffectedSourceLocation, ...]
    allowed_files: tuple[Path, ...]
    protected_files: tuple[Path, ...]
    required_outcome: str
    constraints: tuple[RepairConstraint, ...]
    verification_requirements: tuple[VerificationRequirement, ...]
    verification_commands: tuple[VerificationCommand, ...]
    scope: PlanScope
    cautious_repair: bool
    additional_file_policy: str

    def __post_init__(self) -> None:
        _require_text(self.plan_id, "plan_id")
        _require_text(self.run_id, "run_id")
        _require_text(self.summary, "migration plan summary")
        _require_text(self.required_outcome, "required_outcome")
        _require_text(self.additional_file_policy, "additional_file_policy")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))
        for field_name, paths in (
            ("allowed_files", self.allowed_files),
            ("protected_files", self.protected_files),
        ):
            normalized = tuple(Path(path) for path in paths)
            if any(path.is_absolute() or ".." in path.parts for path in normalized):
                raise ValueError(f"{field_name} must contain repository-relative paths")
            object.__setattr__(self, field_name, normalized)


@dataclass(frozen=True, slots=True)
class RepairContext:
    """Compact Phase 7 input without full logs, dependency trees, or repository."""

    run_id: str
    diagnosis_summary: str
    hypothesis_id: str | None
    plan: MigrationPlan
    source_contexts: tuple[SourceContext, ...]

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.diagnosis_summary, "diagnosis_summary")


@dataclass(frozen=True, slots=True)
class MigrationPlanningResult:
    """Complete Phase 6 output while retaining typed upstream evidence."""

    task: TaskSpec
    evidence: EvidenceBundle
    diagnosis: CausalDiagnosis
    plan: MigrationPlan
    repair_context: RepairContext


@dataclass(frozen=True, slots=True)
class RepairFeedback:
    """Bounded failed-attempt evidence supplied to next provider call."""

    attempt_number: int
    attempt_status: RepairAttemptStatus
    changed_files: tuple[Path, ...]
    summary: str
    primary_failure: FailureSignal | None = None
    bounded_excerpt: str = ""
    safety_issues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("feedback attempt_number must be at least 1")
        _require_text(self.summary, "repair feedback summary")
        normalized = tuple(Path(path) for path in self.changed_files)
        if any(path.is_absolute() or ".." in path.parts for path in normalized):
            raise ValueError("feedback changed_files must be repository-relative")
        object.__setattr__(self, "changed_files", normalized)


@dataclass(frozen=True, slots=True)
class RepairRequest:
    """Exact bounded instruction given to one repair provider."""

    attempt_number: int
    instruction: str
    context: RepairContext
    feedback: RepairFeedback | None = None

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("repair request attempt_number must be at least 1")
        _require_text(self.instruction, "repair instruction")


@dataclass(frozen=True, slots=True)
class RepairProviderResult:
    """Provider observation; never authority for verification."""

    status: RepairProviderStatus
    provider: str
    summary: str
    raw_output: str
    duration_seconds: float
    reported_files: tuple[Path, ...] = ()
    justification: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider, "repair provider")
        _require_text(self.summary, "repair provider summary")
        if self.duration_seconds < 0:
            raise ValueError("provider duration_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class TestFileBaseline:
    """Pre-provider test file and disable-marker count."""

    file: Path
    disable_markers: int

    def __post_init__(self) -> None:
        path = Path(self.file)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("baseline test file must be repository-relative")
        if self.disable_markers < 0:
            raise ValueError("disable_markers must not be negative")
        object.__setattr__(self, "file", path)


@dataclass(frozen=True, slots=True)
class PatchBaseline:
    """Protected pre-repair facts used for delta-only safety analysis."""

    test_files: tuple[TestFileBaseline, ...]
    test_skip_markers: int

    def __post_init__(self) -> None:
        if self.test_skip_markers < 0:
            raise ValueError("test_skip_markers must not be negative")


@dataclass(frozen=True, slots=True)
class PatchStats:
    """Git-derived deterministic patch size."""

    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    files_added: int = 0
    files_deleted: int = 0

    def __post_init__(self) -> None:
        if any(
            value < 0
            for value in (
                self.files_changed,
                self.lines_added,
                self.lines_removed,
                self.files_added,
                self.files_deleted,
            )
        ):
            raise ValueError("patch statistics must not be negative")


@dataclass(frozen=True, slots=True)
class PatchAnalysis:
    """Git-ground-truth changes and deterministic safety findings."""

    patch: str
    changed_files: tuple[Path, ...]
    added_files: tuple[Path, ...]
    deleted_files: tuple[Path, ...]
    out_of_scope_files: tuple[Path, ...]
    evidence_backed_expansions: tuple[Path, ...]
    deleted_test_files: tuple[Path, ...]
    newly_disabled_test_files: tuple[Path, ...]
    test_skip_introduced: bool
    manifest_files_changed: tuple[Path, ...]
    scope_status: PatchScopeStatus
    stats: PatchStats
    fatal_issues: tuple[str, ...] = ()
    review_issues: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        """Return whether Git observed project modifications."""
        return bool(self.changed_files)


@dataclass(frozen=True, slots=True)
class DependencyValidationResult:
    """Resolved target and causal dependency checks after one patch."""

    execution: ExecutionResult
    target_retained: bool
    causal_dependency_retained: bool
    resolved_target_version: str | None
    resolved_causal_version: str | None
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VerificationCheck:
    """One independently computed verification fact."""

    name: str
    status: VerificationCheckStatus
    details: str

    def __post_init__(self) -> None:
        _require_text(self.name, "verification check name")
        _require_text(self.details, "verification check details")



@dataclass(frozen=True, slots=True)
class RepairAttempt:
    """Metadata and execution feedback for one candidate migration."""

    attempt_number: int
    execution: ExecutionResult
    status: RepairAttemptStatus = RepairAttemptStatus.PATCH_CREATED
    provider_result: RepairProviderResult | None = None
    feedback_used: RepairFeedback | None = None
    modified_files: tuple[Path, ...] = ()
    lines_added: int = 0
    lines_removed: int = 0
    patch_path: Path | None = None
    patch_analysis: PatchAnalysis | None = None
    compile_result: ExecutionResult | None = None
    test_result: ExecutionResult | None = None
    dependency_validation: DependencyValidationResult | None = None
    verification: VerificationResult | None = None
    feedback: RepairFeedback | None = None
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.attempt_number < 1:
            raise ValueError("attempt_number must be at least 1")
        if self.lines_added < 0 or self.lines_removed < 0:
            raise ValueError("line counts must not be negative")
        if self.duration_seconds < 0:
            raise ValueError("attempt duration_seconds must not be negative")
        normalized = tuple(Path(path) for path in self.modified_files)
        if any(path.is_absolute() or ".." in path.parts for path in normalized):
            raise ValueError("modified_files must be repository-relative")
        object.__setattr__(self, "modified_files", normalized)
        if self.patch_path is not None:
            object.__setattr__(self, "patch_path", Path(self.patch_path))


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Deterministic checks governing the final migration status."""

    status: VerificationStatus
    target_dependency_retained: bool
    compilation_passed: bool
    tests_passed: bool
    causal_dependency_retained: bool = True
    tests_preserved: bool = True
    tests_enabled: bool = True
    test_execution_not_skipped: bool = True
    patch_scope_acceptable: bool = True
    checks: tuple[VerificationCheck, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepairResult:
    """Final bounded repair-loop result."""

    run_id: str
    status: MigrationStatus
    artifact_directory: Path
    attempts: tuple[RepairAttempt, ...]
    winning_attempt: int | None
    verification: VerificationResult | None
    total_duration_seconds: float
    report: MigrationReport | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "repair result run_id")
        if self.winning_attempt is not None and self.winning_attempt < 1:
            raise ValueError("winning_attempt must be at least 1")
        if self.total_duration_seconds < 0:
            raise ValueError("total_duration_seconds must not be negative")
        object.__setattr__(self, "artifact_directory", Path(self.artifact_directory))


@dataclass(frozen=True, slots=True)
class MigrationReport:
    """Structured final report for a dependency migration task."""

    task: TaskSpec
    status: MigrationStatus
    evidence: EvidenceBundle | None = None
    hypothesis: RootCauseHypothesis | None = None
    attempts: tuple[RepairAttempt, ...] = ()
    verification: VerificationResult | None = None
    diagnosis_summary: str | None = None
    plan_summary: str | None = None
    winning_attempt: int | None = None
    duration_seconds: float = 0.0
    artifact_directory: Path | None = None
