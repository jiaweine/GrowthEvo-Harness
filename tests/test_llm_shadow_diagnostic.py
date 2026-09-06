from __future__ import annotations

from typing import Any, Mapping

from growthevo.bench.causal_evidence import (
    CausalEvidenceBundle,
    EvidenceCaseSpec,
    EvidenceTier,
    StaticCausalOptionEvidenceProducer,
    fixed_reference_estimate,
)
from growthevo.bench.llm_evaluation import LLMExperimentPlan, LLMPolicyCandidate
from growthevo.bench.llm_shadow_runner import ShadowPlannerEntry, run_locked_shadow_benchmark
from growthevo.models import Channel, GrowthConstraints, GrowthGoal, GrowthOption, UserObservation
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.planner import GrowthHypothesis


class _Planner:
    def __init__(self) -> None:
        self._snapshot: dict[str, Any] | None = None

    def plan(self, belief: Any, goal: Any) -> GrowthHypothesis:
        self._snapshot = {
            "used_llm": True,
            "accepted": False,
            "reason": "shadow_only",
            "provider": "fake",
            "model": "fake-v1",
            "proposed_option": GrowthOption.RETAIN.value,
            "returned_option": GrowthOption.UPSELL.value,
            "confidence": 0.9,
            "latency_ms": 1.0,
            "shadow_mode": True,
        }
        return GrowthHypothesis(
            option=GrowthOption.UPSELL,
            rationale="baseline",
            target_metric=goal.metric,
        )

    def audit_snapshot(self) -> Mapping[str, Any] | None:
        return self._snapshot


def _spec(case_id: str) -> EvidenceCaseSpec:
    belief = build_causal_belief(
        UserObservation(
            user_id=case_id,
            natural_conversion=0.2,
            channel_uplift={Channel.PUSH: 0.05},
            uplift_uncertainty=0.05,
            ltv=100.0,
            consented_channels=frozenset({Channel.PUSH}),
        )
    )
    goal = GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=GrowthConstraints(max_budget=100.0),
    )
    return EvidenceCaseSpec(
        case_id=case_id,
        belief=belief,
        goal=goal,
        baseline_option=GrowthOption.UPSELL,
    )


def _bundle(spec: EvidenceCaseSpec) -> CausalEvidenceBundle:
    return CausalEvidenceBundle(
        case_id=spec.case_id,
        context_fingerprint=spec.context_fingerprint,
        estimand="diagnostic_simulated_value",
        producer_name="simulator",
        producer_version="v1",
        estimates=(
            fixed_reference_estimate(
                GrowthOption.UPSELL,
                value=0.0,
                standard_error=0.01,
                tier=EvidenceTier.MODEL_BASED,
                source_id="sim-baseline",
                protocol_fingerprint="sim-v1",
            ),
            fixed_reference_estimate(
                GrowthOption.RETAIN,
                value=1.0,
                standard_error=0.01,
                tier=EvidenceTier.MODEL_BASED,
                source_id="sim-retain",
                protocol_fingerprint="sim-v1",
            ),
        ),
    )


def test_diagnostic_shadow_run_can_score_but_never_promote() -> None:
    validation = _spec("diag-v")
    holdout = _spec("diag-h")
    producer = StaticCausalOptionEvidenceProducer(
        {
            validation.case_id: _bundle(validation),
            holdout.case_id: _bundle(holdout),
        },
        name="simulator",
        version="v1",
    )
    candidate = LLMPolicyCandidate(
        name="candidate",
        provider="fake",
        model="fake-v1",
        contract_fingerprint="contract-v1",
    )
    plan = LLMExperimentPlan(
        benchmark="diagnostic-shadow",
        dataset="simulator",
        dataset_source="unit-test",
        candidates=(candidate,),
        max_fallback_rate=1.0,
    )

    run = run_locked_shadow_benchmark(
        plan=plan,
        entries=(ShadowPlannerEntry(candidate, _Planner()),),
        producer=producer,
        validation_specs=(validation,),
        holdout_specs=(holdout,),
        commit_sha="deadbeef",
        require_promotion_evidence=False,
    )

    assert run.holdout.score.incremental_lcb > 0.0
    assert run.artifact.promotion_eligible is False
    assert run.artifact.metrics["evidence_mode"] == "diagnostic_only"
