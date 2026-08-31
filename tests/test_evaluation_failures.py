from bumpshield.evaluation.failures import classify_provider_failure
from bumpshield.evaluation.models import ProviderFailureKind
from bumpshield.models import RepairProviderResult, RepairProviderStatus


def _provider(
    status: RepairProviderStatus, text: str
) -> RepairProviderResult:
    return RepairProviderResult(status, "fake", text, text, 0.1)


def test_provider_failure_classification_is_conservative() -> None:
    assert classify_provider_failure(
        _provider(RepairProviderStatus.ERROR, "You've hit your usage limit")
    ) is ProviderFailureKind.PROVIDER_QUOTA_EXHAUSTED
    assert classify_provider_failure(
        _provider(RepairProviderStatus.TIMEOUT, "timed out")
    ) is ProviderFailureKind.PROVIDER_TIMEOUT
    assert classify_provider_failure(
        _provider(RepairProviderStatus.UNAVAILABLE, "executable not found")
    ) is ProviderFailureKind.PROVIDER_UNAVAILABLE
    assert classify_provider_failure(
        _provider(RepairProviderStatus.ERROR, "authentication required")
    ) is ProviderFailureKind.PROVIDER_AUTH_FAILURE
    assert classify_provider_failure(
        _provider(RepairProviderStatus.ERROR, "provider exited 1")
    ) is ProviderFailureKind.PROVIDER_NONZERO_EXIT
    assert classify_provider_failure(
        _provider(RepairProviderStatus.ERROR, "opaque failure")
    ) is ProviderFailureKind.PROVIDER_UNKNOWN_ERROR
