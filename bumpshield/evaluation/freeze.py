"""Versioned evaluation configuration loading and stable digests."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bumpshield.agent.investigator import EVIDENCE_WEIGHTS, HARD_CONTRADICTION_SCORE_CAP
from bumpshield.agent.provider import build_repair_request
from bumpshield.config import BumpShieldConfig, MAVEN_TIMEOUT_SECONDS
from bumpshield.evaluation.models import BenchmarkSuite, StrategyId
from bumpshield.evaluation.schedule import SCHEDULING_POLICY_VERSION
from bumpshield.evaluation.strategies import DirectBaselinePlanning, EvaluationStrategy


EVALUATION_VERSION = "BumpShield MVP Evaluation v1"
VERIFICATION_POLICY_VERSION = "independent-verifier-v1"
DIAGNOSIS_POLICY_VERSION = "deterministic-investigator-v1"
PLANNER_POLICY_VERSION = "migration-planner-v1"
CASE_VALIDITY_POLICY_VERSION = "base-pass-updated-fail-target-resolution-v1"
FROZEN_MARKER = "FROZEN FOR FINAL EVALUATION"


class FrozenConfigError(ValueError):
    """Raised when frozen evaluation configuration is malformed or changed."""


@dataclass(frozen=True, slots=True)
class FrozenEvaluationConfig:
    """Validated frozen JSON plus its declared stable digest."""

    path: Path
    configuration: dict[str, Any]
    sha256: str


def prompt_template_hashes() -> dict[str, str]:
    """Hash stable prompt construction code, excluding runtime paths/content."""
    repair = _source_hash(build_repair_request)
    direct = _source_hash(DirectBaselinePlanning.plan, build_repair_request)
    return {
        "direct-one-shot-v1": direct,
        "direct-retry-v1": direct,
        "bumpshield-repair-v1": repair,
    }


def causal_scoring_hash() -> str:
    """Hash normalized deterministic diagnosis weights and hard cap."""
    return stable_digest(
        {
            "weights": dict(sorted(EVIDENCE_WEIGHTS.items())),
            "hard_contradiction_score_cap": HARD_CONTRADICTION_SCORE_CAP,
        }
    )


def runtime_configuration(
    suite: BenchmarkSuite,
    strategies: dict[StrategyId, EvaluationStrategy],
    config: BumpShieldConfig,
) -> dict[str, Any]:
    """Build normalized effective configuration persisted for every run."""
    return {
        "evaluation_version": EVALUATION_VERSION,
        "schema_version": 2,
        "strategies": [item.value for item in suite.strategies],
        "attempt_budgets": {
            item.value: strategies[item].maximum_provider_calls
            for item in suite.strategies
        },
        "strategy_order_policy": SCHEDULING_POLICY_VERSION,
        "trials": suite.trials,
        "repair_provider": config.repair_provider_executable,
        "model": None,
        "provider_timeout_seconds": config.repair_provider_timeout_seconds,
        "maven_timeout_seconds": MAVEN_TIMEOUT_SECONDS,
        "verification_policy": VERIFICATION_POLICY_VERSION,
        "diagnosis_policy": DIAGNOSIS_POLICY_VERSION,
        "planner_policy": PLANNER_POLICY_VERSION,
        "case_validity_policy": CASE_VALIDITY_POLICY_VERSION,
        "prompt_templates": prompt_template_hashes(),
        "causal_scoring_hash": causal_scoring_hash(),
    }


def load_frozen_config(path: Path) -> FrozenEvaluationConfig:
    """Load one self-digesting final-evaluation configuration artifact."""
    resolved = Path(path).expanduser().resolve()
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FrozenConfigError(f"could not load frozen config {resolved}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("configuration"), dict):
        raise FrozenConfigError("frozen config must contain a configuration object")
    declared = data.get("sha256")
    if not isinstance(declared, str) or len(declared) != 64:
        raise FrozenConfigError("frozen config must contain a SHA-256 digest")
    configuration = data["configuration"]
    actual = stable_digest(configuration)
    if actual != declared:
        raise FrozenConfigError("frozen config digest does not match configuration")
    _validate_required(configuration)
    return FrozenEvaluationConfig(resolved, configuration, declared)


def validate_frozen_runtime(
    frozen: FrozenEvaluationConfig,
    effective: dict[str, Any],
) -> None:
    """Reject silent strategy, model, prompt, or policy drift."""
    mismatches = [
        key
        for key in frozen.configuration
        if key not in {"freeze_marker", "unseen_case_policy", "case_composition"}
        and frozen.configuration.get(key) != effective.get(key)
    ]
    if mismatches:
        raise FrozenConfigError(
            "effective evaluation configuration differs from freeze: "
            + ", ".join(sorted(mismatches))
        )


def stable_digest(value: object) -> str:
    """SHA-256 over canonical UTF-8 JSON."""
    normalized = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def _source_hash(*objects: object) -> str:
    return hashlib.sha256(
        "\n".join(inspect.getsource(item) for item in objects).encode("utf-8")
    ).hexdigest()


def _validate_required(configuration: dict[str, Any]) -> None:
    required = {
        "evaluation_version",
        "freeze_marker",
        "schema_version",
        "strategies",
        "attempt_budgets",
        "strategy_order_policy",
        "trials",
        "repair_provider",
        "model",
        "provider_timeout_seconds",
        "maven_timeout_seconds",
        "verification_policy",
        "diagnosis_policy",
        "planner_policy",
        "case_validity_policy",
        "prompt_templates",
        "causal_scoring_hash",
        "unseen_case_policy",
        "case_composition",
    }
    missing = required - configuration.keys()
    if missing:
        raise FrozenConfigError(
            "frozen config missing fields: " + ", ".join(sorted(missing))
        )
    if configuration["freeze_marker"] != FROZEN_MARKER:
        raise FrozenConfigError("frozen config marker is invalid")
