import json
from pathlib import Path

import pytest

from bumpshield.evaluation.freeze import (
    FrozenConfigError,
    causal_scoring_hash,
    load_frozen_config,
    prompt_template_hashes,
    stable_digest,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frozen_final_config_digest_and_policy_hashes_match_code() -> None:
    first = load_frozen_config(PROJECT_ROOT / "benchmark/final-config-v1.json")
    second = load_frozen_config(PROJECT_ROOT / "benchmark/final-config-v1.json")

    assert first == second
    assert first.sha256 == stable_digest(first.configuration)
    assert first.configuration["prompt_templates"] == prompt_template_hashes()
    assert first.configuration["causal_scoring_hash"] == causal_scoring_hash()
    assert first.configuration["strategies"] == [
        "direct-one-shot",
        "direct-retry",
        "bumpshield",
    ]


def test_frozen_config_rejects_digest_drift(tmp_path: Path) -> None:
    source = PROJECT_ROOT / "benchmark/final-config-v1.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    data["configuration"]["trials"] = 3
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(FrozenConfigError, match="digest"):
        load_frozen_config(path)
