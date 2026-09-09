"""Offline smoke test for the production operator path.

This example deliberately uses fake provider transports and synthetic Tier-A-shaped
contract evidence. It validates orchestration only; it is not evidence that any
real GPT/Claude/Gemini snapshot wins a product benchmark.
"""

from __future__ import annotations

import json

from growthevo.bench import (
    CausalEvidenceBundle,
    EvidenceCaseSpec,
    EvidenceTier,
    LLMEndpointSpec,
    LLMExperimentPlan,
    ShadowBenchmarkPlan,
    ShadowCandidateSpec,
    StaticCausalOptionEvidenceProducer,
    build_shadow_candidate,
    fixed_reference_estimate,
    run_locked_shadow_benchmark,
)
from growthevo.models import (
    CausalBelief,
    Channel,
    GrowthConstraints,
    GrowthGoal,
    GrowthOption,
)


class _FakeResponse:
    def __init__(self, option: str) -> None:
        self.output_text = json.dumps(
            {
                "option": option,
                "rationale": "offline operator contract smoke test",
                "confidence": 0.95,
                "exploration_priority": 0.05,
            }
        )


class _FakeResponses:
    def __init__(self, option: str) -> None:
        self.option = option

    def create(self, **_: object) -> _FakeResponse:
        return _FakeResponse(self.option)


class _FakeOpenAI:
    def __init__(self, option: str) -> None:
        self.responses = _FakeResponses(option)


def _spec(case_id: str) -> EvidenceCaseSpec:
    belief = CausalBelief(
        user_id=f"offline-{case_id}",
        natural_conversion=0.10,
        channel_uplift={Channel.EMAIL: 0.03, Channel.PUSH: 0.02},
        uplift_uncertainty=0.10,
        ltv=100.0,
        fatigue=0.10,
        churn_risk=0.35,
        touches_24h=0,
        touches_7d=1,
        spend_to_date=0.0,
        days_since_last_active=2,
        lifecycle_stage="active",
        consented_channels=frozenset({Channel.EMAIL, Channel.PUSH}),
    )
    goal = GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=GrowthConstraints(max_budget=10.0),
    )
    return EvidenceCaseSpec(
        case_id=case_id,
        belief=belief,
        goal=goal,
        baseline_option=GrowthOption.RETAIN,
    )


def _bundle(spec: EvidenceCaseSpec) -> CausalEvidenceBundle:
    protocol = "offline-contract-protocol-v1"
    source = f"offline-contract:{spec.case_id}"
    return CausalEvidenceBundle(
        case_id=spec.case_id,
        context_fingerprint=spec.context_fingerprint,
        estimand="incremental value vs no treatment",
        estimates=(
            fixed_reference_estimate(
                GrowthOption.RETAIN,
                value=0.01,
                standard_error=0.001,
                tier=EvidenceTier.RANDOMIZED_EXPERIMENT,
                source_id=source,
                protocol_fingerprint=protocol,
                sample_size=1000,
            ),
            fixed_reference_estimate(
                GrowthOption.UPSELL,
                value=0.20,
                standard_error=0.001,
                tier=EvidenceTier.RANDOMIZED_EXPERIMENT,
                source_id=source,
                protocol_fingerprint=protocol,
                sample_size=1000,
            ),
        ),
        producer_name="offline-contract-evidence",
        producer_version="v1",
    )


def main() -> None:
    conservative_spec = ShadowCandidateSpec(
        name="baseline-like",
        endpoint=LLMEndpointSpec(provider="openai", model="offline-model-a"),
    )
    causal_spec = ShadowCandidateSpec(
        name="causal-winner",
        endpoint=LLMEndpointSpec(provider="openai", model="offline-model-b"),
    )
    conservative = build_shadow_candidate(
        conservative_spec,
        client_override=_FakeOpenAI("retain"),
    )
    causal = build_shadow_candidate(
        causal_spec,
        client_override=_FakeOpenAI("upsell"),
    )

    plan = LLMExperimentPlan(
        benchmark="offline-operator-smoke",
        dataset="synthetic-semantic-contract",
        dataset_source="example:offline-only",
        candidates=(conservative.candidate, causal.candidate),
        trials_per_case=1,
    )
    validation = (_spec("validation-1"),)
    holdout = (_spec("holdout-1"),)
    producer = StaticCausalOptionEvidenceProducer(
        {
            validation[0].case_id: _bundle(validation[0]),
            holdout[0].case_id: _bundle(holdout[0]),
        },
        name="offline-contract-evidence",
        version="v1",
    )
    result = run_locked_shadow_benchmark(
        plan=ShadowBenchmarkPlan(plan, require_promotion_evidence=True),
        entries=(conservative.entry, causal.entry),
        producer=producer,
        validation_specs=validation,
        holdout_specs=holdout,
        commit_sha="offline-demo-commit",
    )

    assert result.selected_candidate.name == "causal-winner"
    assert result.artifact.promotion_eligible is True
    assert all(
        decision.runtime_option is GrowthOption.RETAIN
        for decision in result.validation_decisions + result.holdout_decisions
    )
    print(
        json.dumps(
            {
                "selected_candidate": result.selected_candidate.name,
                "promotion_eligible": result.artifact.promotion_eligible,
                "shadow_plan_fingerprint": result.shadow_plan_fingerprint,
                "evidence_manifest_fingerprint": result.evidence_manifest_fingerprint,
                "runtime_remained_baseline": True,
                "real_provider_claim": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
