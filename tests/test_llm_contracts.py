from __future__ import annotations

from dataclasses import dataclass

from growthevo.llm import (
    GuardedLLMGrowthPlanner,
    LLMPlannerConfig,
    planner_contract_fingerprint,
    planner_contract_payload,
)


@dataclass
class _Client:
    provider_name: str = "fake"
    model: str = "fake-snapshot-a"

    def generate(self, *, system, user, schema):
        return {
            "option": "upsell",
            "rationale": "fixture",
            "confidence": 0.9,
            "exploration_priority": 0.0,
        }


def test_contract_fingerprint_changes_when_safety_threshold_changes() -> None:
    default = GuardedLLMGrowthPlanner(_Client())
    stricter = GuardedLLMGrowthPlanner(
        _Client(),
        config=LLMPlannerConfig(min_confidence=0.90),
    )

    assert planner_contract_fingerprint(default) != planner_contract_fingerprint(stricter)


def test_contract_fingerprint_changes_when_critic_is_enabled() -> None:
    without_critic = GuardedLLMGrowthPlanner(_Client())
    with_critic = GuardedLLMGrowthPlanner(_Client(), critic=_Client(model="critic-snapshot"))

    assert planner_contract_fingerprint(without_critic) != planner_contract_fingerprint(with_critic)


def test_provider_model_identity_stays_separate_from_harness_contract() -> None:
    first = GuardedLLMGrowthPlanner(_Client(model="snapshot-a"))
    second = GuardedLLMGrowthPlanner(_Client(model="snapshot-b"))

    assert planner_contract_fingerprint(first) == planner_contract_fingerprint(second)


def test_contract_payload_does_not_contain_provider_credentials_or_model_name() -> None:
    planner = GuardedLLMGrowthPlanner(_Client(model="private-model-id"))
    payload = planner_contract_payload(planner)
    rendered = str(payload)

    assert payload["schema_version"] == "growthevo.llm-planner-contract.v1"
    assert "private-model-id" not in rendered
    assert "system_prompt" in payload
    assert "proposal_schema" in payload
    assert "config" in payload
