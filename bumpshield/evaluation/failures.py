"""Deterministic benchmark failure classification and circuit-breaker policy."""

from __future__ import annotations

from bumpshield.evaluation.models import (
    FailureDomain,
    FailureReason,
    ProviderFailureKind,
)
from bumpshield.models import (
    MigrationStatus,
    RepairAttemptStatus,
    RepairProviderResult,
    RepairProviderStatus,
    RepairResult,
)


GLOBAL_PROVIDER_FAILURES = frozenset(
    {
        ProviderFailureKind.PROVIDER_UNAVAILABLE,
        ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED,
        ProviderFailureKind.PROVIDER_AUTH_FAILURE,
        ProviderFailureKind.PROVIDER_SERVICE_UNAVAILABLE,
    }
)

_QUOTA_PATTERNS = (
    "usage limit",
    "quota exceeded",
    "rate limit",
    "too many requests",
    "insufficient_quota",
)
_AUTH_PATTERNS = (
    "authentication failed",
    "authentication required",
    "not authenticated",
    "unauthorized",
    "invalid api key",
    "login required",
    "not logged in",
)
_SERVICE_PATTERNS = (
    "service unavailable",
    "temporarily unavailable",
    "provider unavailable",
    "connection refused",
)


def classify_provider_failure(
    provider: RepairProviderResult | None,
) -> ProviderFailureKind | None:
    """Classify only explicit provider failure evidence."""
    if provider is None or provider.status is RepairProviderStatus.SUCCESS:
        return None
    if provider.status is RepairProviderStatus.UNAVAILABLE:
        return ProviderFailureKind.PROVIDER_UNAVAILABLE
    if provider.status is RepairProviderStatus.TIMEOUT:
        return ProviderFailureKind.PROVIDER_TIMEOUT
    text = f"{provider.summary}\n{provider.raw_output}".casefold()
    if any(pattern in text for pattern in _QUOTA_PATTERNS):
        return ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED
    if any(pattern in text for pattern in _AUTH_PATTERNS):
        return ProviderFailureKind.PROVIDER_AUTH_FAILURE
    if any(pattern in text for pattern in _SERVICE_PATTERNS):
        return ProviderFailureKind.PROVIDER_SERVICE_UNAVAILABLE
    if "exited" in text or "exit code" in text:
        return ProviderFailureKind.PROVIDER_NONZERO_EXIT
    return ProviderFailureKind.PROVIDER_UNKNOWN_ERROR


def repair_provider_failure(result: RepairResult) -> ProviderFailureKind | None:
    """Return last provider failure from one completed strategy trial."""
    for attempt in reversed(result.attempts):
        failure = classify_provider_failure(attempt.provider_result)
        if failure is not None:
            return failure
    return None


def failure_domain(
    result: RepairResult,
    reason: FailureReason | None,
    provider_failure: ProviderFailureKind | None,
) -> FailureDomain | None:
    """Assign one stable research domain without parsing report prose."""
    if result.status is MigrationStatus.VERIFIED_MIGRATION:
        return None
    if provider_failure is not None:
        return FailureDomain.PROVIDER
    if reason is FailureReason.INFRASTRUCTURE_ERROR:
        return FailureDomain.INFRASTRUCTURE
    if reason in {
        FailureReason.DEPENDENCY_GUARD,
        FailureReason.TEST_INTEGRITY_VIOLATION,
        FailureReason.PATCH_SCOPE_REVIEW,
    }:
        return FailureDomain.VERIFICATION
    if result.attempts and result.attempts[-1].status is RepairAttemptStatus.EXECUTION_ERROR:
        return FailureDomain.INFRASTRUCTURE
    return FailureDomain.REPAIR


def is_global_provider_failure(kind: ProviderFailureKind | None) -> bool:
    """Return whether later provider-backed trials should pause."""
    return kind in GLOBAL_PROVIDER_FAILURES
