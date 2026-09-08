from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from growthevo.llm.contracts import planner_contract_fingerprint
from growthevo.llm.planner import GuardedLLMGrowthPlanner, LLMPlannerConfig
from growthevo.llm.providers import AnthropicToolClient, GeminiStructuredClient, OpenAIResponsesClient
from growthevo.runtime.planner import GrowthHypothesisPlanner

from ._serialization import fingerprint_json
from .llm_evaluation import LLMPolicyCandidate
from .llm_shadow_runner import ShadowPlannerEntry


ProviderName = Literal["openai", "anthropic", "google"]


@dataclass(frozen=True, slots=True)
class LLMEndpointSpec:
    """Non-secret, pre-registrable model endpoint configuration.

    Authentication is deliberately absent. Provider SDKs resolve credentials by
    their normal environment/identity mechanisms, keeping secrets out of
    benchmark plans, fingerprints, event logs and serialized artifacts.
    """

    provider: ProviderName
    model: str
    reasoning_effort: str | None = None
    store: bool = False
    max_tokens: int = 900

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("model cannot be empty")
        if self.provider not in {"openai", "anthropic", "google"}:
            raise ValueError(f"unsupported LLM provider: {self.provider}")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.provider != "openai" and self.reasoning_effort is not None:
            raise ValueError("reasoning_effort is currently supported only for OpenAI")
        if self.provider != "openai" and self.store:
            raise ValueError("store is currently an OpenAI-only endpoint setting")

    def behavior_payload(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "provider": self.provider,
            "model": self.model,
        }
        if self.provider == "openai":
            base.update(
                {
                    "reasoning_effort": self.reasoning_effort,
                    "store": self.store,
                }
            )
        elif self.provider == "anthropic":
            base["max_tokens"] = self.max_tokens
        else:
            # Gemini adapter currently pins temperature=0 and strict JSON schema
            # in code; those settings are captured by the factory schema/version.
            base["structured_output_mode"] = "generate_content_response_json_schema_temperature_0"
        return base


@dataclass(frozen=True, slots=True)
class ShadowCandidateSpec:
    name: str
    endpoint: LLMEndpointSpec
    planner_config: LLMPlannerConfig = field(
        default_factory=lambda: LLMPlannerConfig(shadow_mode=True)
    )
    critic_endpoint: LLMEndpointSpec | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("candidate name cannot be empty")
        if not self.planner_config.shadow_mode:
            raise ValueError("shadow candidate factory requires planner_config.shadow_mode=True")


@dataclass(frozen=True, slots=True)
class BuiltShadowCandidate:
    spec: ShadowCandidateSpec
    candidate: LLMPolicyCandidate
    planner: GuardedLLMGrowthPlanner
    entry: ShadowPlannerEntry


class _ContractOnlyClient:
    """Provider-shaped identity stub used only for offline preregistration."""

    def __init__(self, endpoint: LLMEndpointSpec) -> None:
        self.provider_name = endpoint.provider
        self.model = endpoint.model

    def generate(self, **_: Any) -> Any:  # pragma: no cover - defensive only
        raise RuntimeError("contract-only client cannot make model requests")


def _build_client(endpoint: LLMEndpointSpec, client_override: Any | None) -> Any:
    if endpoint.provider == "openai":
        return OpenAIResponsesClient(
            model=endpoint.model,
            client=client_override,
            reasoning_effort=endpoint.reasoning_effort,
            store=endpoint.store,
        )
    if endpoint.provider == "anthropic":
        return AnthropicToolClient(
            model=endpoint.model,
            client=client_override,
            max_tokens=endpoint.max_tokens,
        )
    if endpoint.provider == "google":
        return GeminiStructuredClient(
            model=endpoint.model,
            client=client_override,
        )
    raise AssertionError(f"unreachable provider: {endpoint.provider}")


def _candidate_contract_fingerprint(
    *,
    spec: ShadowCandidateSpec,
    planner: GuardedLLMGrowthPlanner,
) -> str:
    return fingerprint_json(
        {
            "schema": "growthevo.shadow-candidate-contract.v1",
            "planner_contract_fingerprint": planner_contract_fingerprint(planner),
            "endpoint": spec.endpoint.behavior_payload(),
            "critic_endpoint": (
                spec.critic_endpoint.behavior_payload()
                if spec.critic_endpoint is not None
                else None
            ),
            "planner_config": asdict(spec.planner_config),
        }
    )


def _candidate_from_planner(
    *,
    spec: ShadowCandidateSpec,
    planner: GuardedLLMGrowthPlanner,
) -> LLMPolicyCandidate:
    contract_fingerprint = _candidate_contract_fingerprint(spec=spec, planner=planner)
    return LLMPolicyCandidate(
        name=spec.name,
        provider=spec.endpoint.provider,
        model=spec.endpoint.model,
        contract_fingerprint=contract_fingerprint,
        critic_provider=(
            spec.critic_endpoint.provider if spec.critic_endpoint is not None else None
        ),
        critic_model=(
            spec.critic_endpoint.model if spec.critic_endpoint is not None else None
        ),
    )


def shadow_candidate_metadata(
    spec: ShadowCandidateSpec,
    *,
    fallback: GrowthHypothesisPlanner | None = None,
) -> LLMPolicyCandidate:
    """Compute exact candidate identity without importing SDKs or reading credentials.

    This is the preregistration path used by production operator manifests. It
    instantiates only the guarded planner contract with non-callable identity
    stubs; no provider client is created and no network call can occur.
    """

    contract_planner = GuardedLLMGrowthPlanner(
        _ContractOnlyClient(spec.endpoint),
        fallback=fallback,
        critic=(
            _ContractOnlyClient(spec.critic_endpoint)
            if spec.critic_endpoint is not None
            else None
        ),
        config=spec.planner_config,
    )
    return _candidate_from_planner(spec=spec, planner=contract_planner)


def build_shadow_candidate(
    spec: ShadowCandidateSpec,
    *,
    client_override: Any | None = None,
    critic_client_override: Any | None = None,
    fallback: GrowthHypothesisPlanner | None = None,
) -> BuiltShadowCandidate:
    """Build a benchmark candidate without accepting or persisting credentials."""

    client = _build_client(spec.endpoint, client_override)
    critic = (
        _build_client(spec.critic_endpoint, critic_client_override)
        if spec.critic_endpoint is not None
        else None
    )
    planner = GuardedLLMGrowthPlanner(
        client,
        fallback=fallback,
        critic=critic,
        config=spec.planner_config,
    )
    candidate = _candidate_from_planner(spec=spec, planner=planner)
    preregistered = shadow_candidate_metadata(spec, fallback=fallback)
    if candidate != preregistered:  # pragma: no cover - invariant tripwire
        raise RuntimeError("runtime candidate identity differs from offline contract identity")
    entry = ShadowPlannerEntry(candidate=candidate, planner=planner)
    return BuiltShadowCandidate(
        spec=spec,
        candidate=candidate,
        planner=planner,
        entry=entry,
    )
