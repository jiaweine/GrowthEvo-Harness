from __future__ import annotations

import json
from pathlib import Path

import pytest

from growthevo.bench.llm_candidate_factory import LLMEndpointSpec
from growthevo import operator_cli


def _manifest() -> dict:
    return {
        "schema_version": "growthevo.production-operator-manifest.v1",
        "benchmark": "operator-hardening-test",
        "dataset": "synthetic-semantic-cases",
        "dataset_source": "test:synthetic",
        "evidence_producer": {"name": "test-evidence", "version": "v1"},
        "candidates": [
            {
                "name": "openai-shadow",
                "endpoint": {
                    "provider": "openai",
                    "model": "pinned-test-model",
                    "reasoning_effort": "medium",
                    "store": False,
                },
                "planner_config": {"shadow_mode": True},
            }
        ],
    }


def test_provider_irrelevant_endpoint_overrides_fail_closed() -> None:
    with pytest.raises(ValueError, match="max_tokens is currently configurable only for Anthropic"):
        LLMEndpointSpec(provider="openai", model="pinned", max_tokens=123)

    with pytest.raises(ValueError, match="max_tokens is currently configurable only for Anthropic"):
        LLMEndpointSpec(provider="google", model="pinned", max_tokens=123)

    assert LLMEndpointSpec(provider="anthropic", model="pinned", max_tokens=123).max_tokens == 123


def test_doctor_default_is_explicitly_offline_and_never_claims_instantiation_is_offline(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(operator_cli, "_module_available", lambda _: True)

    assert operator_cli.main(["doctor", "--manifest", str(manifest)]) == 0
    payload = json.loads(capsys.readouterr().out)
    doctor = payload["doctor"]
    assert doctor["model_requests_made"] is False
    assert doctor["pure_offline_preflight"] is True
    assert doctor["instantiate_requested"] is False
    assert "network_calls_made" not in doctor
