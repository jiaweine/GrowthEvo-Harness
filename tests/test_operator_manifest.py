from __future__ import annotations

import pytest

from growthevo.bench.llm_candidate_factory import (
    LLMEndpointSpec,
    ShadowCandidateSpec,
    build_shadow_candidate,
    shadow_candidate_metadata,
)
from growthevo.llm.planner import LLMPlannerConfig
from growthevo.operator_manifest import ProductionOperatorManifest


class _FakeOpenAIResponse:
    output_text = '{"option":"retain","rationale":"stable","confidence":0.9,"exploration_priority":0.1}'


class _FakeResponses:
    def create(self, **kwargs):
        return _FakeOpenAIResponse()


class _FakeOpenAI:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


def _payload(*, reasoning_effort: str = "medium") -> dict:
    return {
        "schema_version": "growthevo.production-operator-manifest.v1",
        "benchmark": "operator-contract-test",
        "dataset": "synthetic-semantic-cases",
        "dataset_source": "test:synthetic",
        "evidence_producer": {"name": "test-evidence", "version": "v1"},
        "candidates": [
            {
                "name": "openai-shadow",
                "endpoint": {
                    "provider": "openai",
                    "model": "pinned-test-model",
                    "reasoning_effort": reasoning_effort,
                    "store": False,
                },
                "planner_config": {"shadow_mode": True},
            }
        ],
    }


def test_operator_manifest_preregisters_candidate_without_provider_sdk() -> None:
    manifest = ProductionOperatorManifest.from_mapping(_payload())

    assert manifest.schema_version == "growthevo.production-operator-manifest.v1"
    assert len(manifest.llm_plan.candidates) == 1
    assert len(manifest.fingerprint) == 40
    assert len(manifest.llm_plan.fingerprint) == 40
    assert len(manifest.shadow_plan.fingerprint) == 40
    assert manifest.llm_plan.candidates[0] == shadow_candidate_metadata(
        manifest.candidates[0]
    )


def test_runtime_candidate_identity_matches_offline_preregistration() -> None:
    spec = ShadowCandidateSpec(
        name="openai-shadow",
        endpoint=LLMEndpointSpec(
            provider="openai",
            model="pinned-test-model",
            reasoning_effort="medium",
        ),
        planner_config=LLMPlannerConfig(shadow_mode=True),
    )

    preregistered = shadow_candidate_metadata(spec)
    built = build_shadow_candidate(spec, client_override=_FakeOpenAI())

    assert built.candidate == preregistered


def test_candidate_fingerprint_changes_with_reasoning_contract() -> None:
    medium = ProductionOperatorManifest.from_mapping(
        _payload(reasoning_effort="medium")
    )
    high = ProductionOperatorManifest.from_mapping(_payload(reasoning_effort="high"))

    assert medium.llm_plan.candidates[0].contract_fingerprint != high.llm_plan.candidates[0].contract_fingerprint
    assert medium.fingerprint != high.fingerprint


def test_operator_manifest_rejects_secret_shaped_or_unknown_fields() -> None:
    payload = _payload()
    payload["api_key"] = "must-not-be-accepted"

    with pytest.raises(ValueError, match="unexpected keys"):
        ProductionOperatorManifest.from_mapping(payload)


def test_operator_manifest_requires_shadow_only_candidates() -> None:
    payload = _payload()
    payload["candidates"][0]["planner_config"] = {"shadow_mode": False}

    with pytest.raises(ValueError, match="shadow candidate factory requires"):
        ProductionOperatorManifest.from_mapping(payload)
