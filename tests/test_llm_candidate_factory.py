from __future__ import annotations

import pytest

from growthevo.bench.llm_candidate_factory import (
    LLMEndpointSpec,
    ShadowCandidateSpec,
    build_shadow_candidate,
)
from growthevo.llm.planner import LLMPlannerConfig


class _DummySDKClient:
    pass


def test_openai_shadow_candidate_is_built_without_credentials_in_spec() -> None:
    spec = ShadowCandidateSpec(
        name="openai-high",
        endpoint=LLMEndpointSpec(
            provider="openai",
            model="pinned-openai-snapshot",
            reasoning_effort="high",
            store=False,
        ),
    )

    built = build_shadow_candidate(spec, client_override=_DummySDKClient())

    assert built.candidate.name == "openai-high"
    assert built.candidate.provider == "openai"
    assert built.candidate.model == "pinned-openai-snapshot"
    assert built.entry.planner is built.planner
    assert built.planner.config.shadow_mode is True
    assert "key" not in str(spec).lower()
    assert "token" not in spec.endpoint.behavior_payload()


def test_reasoning_effort_changes_candidate_contract_fingerprint() -> None:
    low = build_shadow_candidate(
        ShadowCandidateSpec(
            name="openai-low",
            endpoint=LLMEndpointSpec(
                provider="openai",
                model="same-snapshot",
                reasoning_effort="low",
            ),
        ),
        client_override=_DummySDKClient(),
    )
    high = build_shadow_candidate(
        ShadowCandidateSpec(
            name="openai-high",
            endpoint=LLMEndpointSpec(
                provider="openai",
                model="same-snapshot",
                reasoning_effort="high",
            ),
        ),
        client_override=_DummySDKClient(),
    )

    assert low.candidate.model == high.candidate.model
    assert low.candidate.contract_fingerprint != high.candidate.contract_fingerprint


def test_anthropic_max_tokens_changes_candidate_contract_fingerprint() -> None:
    short = build_shadow_candidate(
        ShadowCandidateSpec(
            name="anthropic-short",
            endpoint=LLMEndpointSpec(
                provider="anthropic",
                model="same-claude-snapshot",
                max_tokens=500,
            ),
        ),
        client_override=_DummySDKClient(),
    )
    long = build_shadow_candidate(
        ShadowCandidateSpec(
            name="anthropic-long",
            endpoint=LLMEndpointSpec(
                provider="anthropic",
                model="same-claude-snapshot",
                max_tokens=1200,
            ),
        ),
        client_override=_DummySDKClient(),
    )

    assert short.candidate.contract_fingerprint != long.candidate.contract_fingerprint


def test_shadow_factory_rejects_active_planner_config() -> None:
    with pytest.raises(ValueError, match="shadow_mode=True"):
        ShadowCandidateSpec(
            name="active-by-mistake",
            endpoint=LLMEndpointSpec(provider="google", model="gemini-pinned"),
            planner_config=LLMPlannerConfig(shadow_mode=False),
        )


def test_critic_identity_is_part_of_candidate_metadata_and_contract() -> None:
    without_critic = build_shadow_candidate(
        ShadowCandidateSpec(
            name="no-critic",
            endpoint=LLMEndpointSpec(provider="google", model="gemini-pinned"),
        ),
        client_override=_DummySDKClient(),
    )
    with_critic = build_shadow_candidate(
        ShadowCandidateSpec(
            name="with-critic",
            endpoint=LLMEndpointSpec(provider="google", model="gemini-pinned"),
            critic_endpoint=LLMEndpointSpec(
                provider="anthropic",
                model="claude-critic-pinned",
                max_tokens=600,
            ),
        ),
        client_override=_DummySDKClient(),
        critic_client_override=_DummySDKClient(),
    )

    assert with_critic.candidate.critic_provider == "anthropic"
    assert with_critic.candidate.critic_model == "claude-critic-pinned"
    assert without_critic.candidate.contract_fingerprint != with_critic.candidate.contract_fingerprint


def test_provider_specific_endpoint_fields_are_rejected_when_misapplied() -> None:
    with pytest.raises(ValueError, match="only for OpenAI"):
        LLMEndpointSpec(
            provider="anthropic",
            model="claude-pinned",
            reasoning_effort="high",
        )
    with pytest.raises(ValueError, match="OpenAI-only"):
        LLMEndpointSpec(
            provider="google",
            model="gemini-pinned",
            store=True,
        )
