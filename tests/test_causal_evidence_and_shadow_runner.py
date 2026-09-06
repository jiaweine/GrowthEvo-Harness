from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from growthevo.bench.causal_evidence import (
    CausalEvidenceBundle,
    CausalOptionEstimate,
    EvidenceCaseSpec,
    EvidenceTier,
    StaticCausalOptionEvidenceProducer,
    fixed_reference_estimate,
    preregistered_ope_estimate,
    randomized_targeting_estimate,
)
from growthevo.bench.llm_evaluation import LLMExperimentPlan, LLMPolicyCandidate
from growthevo.bench.llm_shadow_runner import ShadowPlannerEntry, run_locked_shadow_benchmark
from growthevo.bench.real_world import RandomizedTargetingResult
from growthevo.bench.statistics import TargetingInferenceResult
from growthevo.models import Channel, GrowthConstraints, GrowthGoal, GrowthOption, UserObservation
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.planner import GrowthHypothesis


def _goal() -> GrowthGoal:
    return GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=GrowthConstraints(max_budget=100.0),
    )


def _spec(case_id: str, *, churn_risk: float = 0.10) -> EvidenceCaseSpec:
    observation = UserObservation(
        user_id=f"user-{case_id}",
        natural_conversion=0.20,
        channel_uplift={Channel.PUSH: 0.08, Channel.EMAIL: 0.04},
        uplift_uncertainty=0.05,
        ltv=100.0,
        churn_risk=churn_risk,
        consented_channels=frozenset({Channel.PUSH, Channel.EMAIL}),
    )
    return EvidenceCaseSpec(
        case_id=case_id,
        belief=build_causal_belief(observation),
        goal=_goal(),
        baseline_option=GrowthOption.UPSELL,
    )


def _estimate(
    option: GrowthOption,
    value: float,
    *,
    tier: EvidenceTier = EvidenceTier.RANDOMIZED_EXPERIMENT,
    source: str = "locked-source",
) -> CausalOptionEstimate:
    return fixed_reference_estimate(
        option,
        value=value,
        standard_error=0.01,
        tier=tier,
        source_id=source,
        protocol_fingerprint="protocol-fingerprint-v1",
        support_coverage=0.99,
        effective_sample_ratio=0.80,
        sample_size=1000,
    )


def _bundle(
    spec: EvidenceCaseSpec,
    estimates: tuple[CausalOptionEstimate, ...],
    *,
    producer_name: str = "locked",
    producer_version: str = "v1",
) -> CausalEvidenceBundle:
    return CausalEvidenceBundle(
        case_id=spec.case_id,
        context_fingerprint=spec.context_fingerprint,
        estimand="incremental_value_vs_no_treatment",
        estimates=estimates,
        producer_name=producer_name,
        producer_version=producer_version,
    )


class AuditedShadowPlanner:
    def __init__(self, proposed: GrowthOption) -> None:
        self.proposed = proposed
        self.calls = 0
        self._snapshot: dict[str, Any] | None = None

    def plan(self, belief: Any, goal: Any) -> GrowthHypothesis:
        self.calls += 1
        self._snapshot = {
            "used_llm": True,
            "accepted": False,
            "reason": "shadow_only",
            "provider": "fake",
            "model": "fake-pinned",
            "proposed_option": self.proposed.value,
            "returned_option": GrowthOption.UPSELL.value,
            "confidence": 0.90,
            "latency_ms": 5.0,
            "shadow_mode": True,
        }
        return GrowthHypothesis(
            option=GrowthOption.UPSELL,
            rationale="deterministic runtime baseline",
            target_metric=goal.metric,
        )

    def audit_snapshot(self) -> Mapping[str, Any] | None:
        return self._snapshot


def test_promotion_case_filters_model_based_and_proxy_evidence() -> None:
    spec = _spec("validation-1")
    bundle = _bundle(
        spec,
        (
            _estimate(GrowthOption.UPSELL, 1.0),
            _estimate(
                GrowthOption.RETAIN,
                9.0,
                tier=EvidenceTier.MODEL_BASED,
                source="simulator",
            ),
            _estimate(
                GrowthOption.REACTIVATE,
                12.0,
                tier=EvidenceTier.PROXY,
                source="heuristic",
            ),
        ),
    )

    case = bundle.to_benchmark_case(spec, require_promotion_evidence=True)

    assert set(case.option_evidence) == {GrowthOption.UPSELL}


def test_diagnostic_case_can_retain_lower_tier_evidence() -> None:
    spec = _spec("diagnostic-1")
    bundle = _bundle(
        spec,
        (
            _estimate(GrowthOption.UPSELL, 1.0),
            _estimate(GrowthOption.RETAIN, 2.0, tier=EvidenceTier.MODEL_BASED),
        ),
    )

    case = bundle.to_benchmark_case(spec, require_promotion_evidence=False)

    assert GrowthOption.RETAIN in case.option_evidence


def test_promotion_requires_promotion_grade_baseline() -> None:
    spec = _spec("validation-2")
    bundle = _bundle(
        spec,
        (
            _estimate(GrowthOption.UPSELL, 1.0, tier=EvidenceTier.MODEL_BASED),
            _estimate(GrowthOption.RETAIN, 2.0),
        ),
    )

    with pytest.raises(ValueError, match="baseline option lacks promotion-eligible"):
        bundle.to_benchmark_case(spec, require_promotion_evidence=True)


def test_static_producer_rejects_context_drift() -> None:
    original = _spec("case-drift", churn_risk=0.10)
    changed = _spec("case-drift", churn_risk=0.40)
    bundle = _bundle(original, (_estimate(GrowthOption.UPSELL, 1.0),))
    producer = StaticCausalOptionEvidenceProducer(
        {original.case_id: bundle},
        name="locked",
        version="v1",
    )

    with pytest.raises(ValueError, match="does not match current case context"):
        producer.produce(changed)


def test_randomized_targeting_adapter_is_tier_a() -> None:
    point = RandomizedTargetingResult(
        sample_size=1000,
        selected_fraction=0.1,
        policy_value=0.12,
        treat_none_value=0.08,
        treat_all_value=0.10,
        incremental_value_vs_none=0.04,
    )
    result = TargetingInferenceResult(
        point=point,
        confidence_level=0.95,
        standard_error=0.005,
        lower_incremental_value=0.03,
        upper_incremental_value=0.05,
        selected_incremental_value=0.40,
        selected_standard_error=0.05,
        lower_selected_incremental_value=0.30,
        upper_selected_incremental_value=0.50,
    )

    evidence = randomized_targeting_estimate(
        GrowthOption.RETAIN,
        result,
        source_id="randomized-campaign-2026q3",
        protocol_fingerprint="randomized-plan-fp",
        support_coverage=1.0,
        effective_sample_ratio=0.50,
    )

    assert evidence.tier is EvidenceTier.RANDOMIZED_EXPERIMENT
    assert evidence.value == pytest.approx(0.04)
    assert evidence.standard_error == pytest.approx(0.005)
    assert evidence.sample_size == 1000


def test_ope_adapter_carries_support_diagnostics_as_tier_b() -> None:
    estimate = SimpleNamespace(
        doubly_robust=0.27,
        dr_standard_error=0.02,
        support_coverage=0.98,
        effective_sample_ratio=0.31,
        sample_size=4000,
    )

    evidence = preregistered_ope_estimate(
        GrowthOption.RETAIN,
        estimate,  # type: ignore[arg-type]
        estimator="doubly_robust",
        source_id="locked-ope-holdout",
        protocol_fingerprint="ope-plan-fp",
    )

    assert evidence.tier is EvidenceTier.PREREGISTERED_OPE
    assert evidence.value == pytest.approx(0.27)
    assert evidence.standard_error == pytest.approx(0.02)
    assert evidence.support_coverage == pytest.approx(0.98)
    assert evidence.effective_sample_ratio == pytest.approx(0.31)


def test_locked_shadow_runner_invokes_only_validation_winner_on_holdout() -> None:
    validation_specs = (_spec("v1"), _spec("v2"))
    holdout_specs = (_spec("h1"), _spec("h2"))
    bundles: dict[str, CausalEvidenceBundle] = {}
    for spec in (*validation_specs, *holdout_specs):
        bundles[spec.case_id] = _bundle(
            spec,
            (
                _estimate(GrowthOption.UPSELL, 1.0),
                _estimate(GrowthOption.RETAIN, 2.0),
                _estimate(GrowthOption.REACTIVATE, 0.5),
            ),
        )
    producer = StaticCausalOptionEvidenceProducer(
        bundles,
        name="locked",
        version="v1",
    )

    retain_candidate = LLMPolicyCandidate(
        name="retain-model",
        provider="fake",
        model="fake-retain-v1",
        contract_fingerprint="contract-retain",
    )
    reactivate_candidate = LLMPolicyCandidate(
        name="reactivate-model",
        provider="fake",
        model="fake-reactivate-v1",
        contract_fingerprint="contract-reactivate",
    )
    plan = LLMExperimentPlan(
        benchmark="llm-shadow-test",
        dataset="locked-fixture",
        dataset_source="unit-test",
        candidates=(retain_candidate, reactivate_candidate),
        max_fallback_rate=1.0,
    )
    retain_planner = AuditedShadowPlanner(GrowthOption.RETAIN)
    reactivate_planner = AuditedShadowPlanner(GrowthOption.REACTIVATE)

    run = run_locked_shadow_benchmark(
        plan=plan,
        entries=(
            ShadowPlannerEntry(retain_candidate, retain_planner),
            ShadowPlannerEntry(reactivate_candidate, reactivate_planner),
        ),
        producer=producer,
        validation_specs=validation_specs,
        holdout_specs=holdout_specs,
        commit_sha="deadbeef",
    )

    assert run.selected_candidate == retain_candidate
    assert run.artifact.selected_candidate == "retain-model"
    assert run.artifact.promotion_eligible is True
    assert retain_planner.calls == len(validation_specs) + len(holdout_specs)
    assert reactivate_planner.calls == len(validation_specs)
    assert {decision.candidate_name for decision in run.holdout_decisions} == {"retain-model"}
    assert run.validation_evidence_fingerprint != run.holdout_evidence_fingerprint
    assert len(run.evidence_manifest_fingerprint) == 40


def test_runner_rejects_producer_identity_mismatch() -> None:
    spec = _spec("identity-1")
    bundle = _bundle(
        spec,
        (_estimate(GrowthOption.UPSELL, 1.0),),
        producer_name="other-producer",
    )
    producer = StaticCausalOptionEvidenceProducer(
        {spec.case_id: bundle},
        name="locked",
        version="v1",
    )
    candidate = LLMPolicyCandidate(
        name="candidate",
        provider="fake",
        model="fake-v1",
        contract_fingerprint="contract",
    )
    plan = LLMExperimentPlan(
        benchmark="identity-test",
        dataset="fixture",
        dataset_source="unit-test",
        candidates=(candidate,),
        max_fallback_rate=1.0,
    )

    with pytest.raises(ValueError, match="producer identity"):
        run_locked_shadow_benchmark(
            plan=plan,
            entries=(ShadowPlannerEntry(candidate, AuditedShadowPlanner(GrowthOption.UPSELL)),),
            producer=producer,
            validation_specs=(spec,),
            holdout_specs=(_spec("identity-holdout"),),
            commit_sha="deadbeef",
        )
