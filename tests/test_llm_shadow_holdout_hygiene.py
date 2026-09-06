from __future__ import annotations

from typing import Any, Mapping

from growthevo.bench.causal_evidence import (
    CausalEvidenceBundle,
    EvidenceCaseSpec,
    EvidenceTier,
    fixed_reference_estimate,
)
from growthevo.bench.llm_evaluation import LLMExperimentPlan, LLMPolicyCandidate
from growthevo.bench.llm_shadow_runner import ShadowPlannerEntry, run_locked_shadow_benchmark
from growthevo.models import Channel, GrowthConstraints, GrowthGoal, GrowthOption, UserObservation
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.planner import GrowthHypothesis


def _spec(case_id: str) -> EvidenceCaseSpec:
    return EvidenceCaseSpec(
        case_id=case_id,
        belief=build_causal_belief(
            UserObservation(
                user_id=case_id,
                natural_conversion=0.2,
                channel_uplift={Channel.PUSH: 0.05},
                uplift_uncertainty=0.05,
                ltv=100.0,
                consented_channels=frozenset({Channel.PUSH}),
            )
        ),
        goal=GrowthGoal(
            metric="incremental_ltv",
            horizon_days=30,
            target_delta=0.05,
            constraints=GrowthConstraints(max_budget=100.0),
        ),
        baseline_option=GrowthOption.UPSELL,
    )


def _bundle(spec: EvidenceCaseSpec) -> CausalEvidenceBundle:
    return CausalEvidenceBundle(
        case_id=spec.case_id,
        context_fingerprint=spec.context_fingerprint,
        estimand="incremental_value_vs_no_treatment",
        producer_name="recording",
        producer_version="v1",
        estimates=(
            fixed_reference_estimate(
                GrowthOption.UPSELL,
                value=0.0,
                standard_error=0.01,
                tier=EvidenceTier.RANDOMIZED_EXPERIMENT,
                source_id="baseline",
                protocol_fingerprint="experiment-v1",
            ),
            fixed_reference_estimate(
                GrowthOption.RETAIN,
                value=1.0,
                standard_error=0.01,
                tier=EvidenceTier.RANDOMIZED_EXPERIMENT,
                source_id="retain",
                protocol_fingerprint="experiment-v1",
            ),
        ),
    )


class _RecordingProducer:
    name = "recording"
    version = "v1"

    def __init__(self, bundles: Mapping[str, CausalEvidenceBundle], events: list[str]) -> None:
        self._bundles = dict(bundles)
        self.events = events

    def produce(self, spec: EvidenceCaseSpec) -> CausalEvidenceBundle:
        self.events.append(f"evidence:{spec.case_id}")
        return self._bundles[spec.case_id]


class _RecordingPlanner:
    def __init__(self, candidate_name: str, events: list[str]) -> None:
        self.candidate_name = candidate_name
        self.events = events
        self._snapshot: dict[str, Any] | None = None

    def plan(self, belief: Any, goal: Any) -> GrowthHypothesis:
        self.events.append(f"planner:{self.candidate_name}")
        self._snapshot = {
            "used_llm": True,
            "accepted": False,
            "reason": "shadow_only",
            "provider": "fake",
            "model": self.candidate_name,
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


def test_holdout_evidence_is_not_requested_before_validation_planners_run() -> None:
    events: list[str] = []
    validation = _spec("validation")
    holdout = _spec("holdout")
    producer = _RecordingProducer(
        {
            validation.case_id: _bundle(validation),
            holdout.case_id: _bundle(holdout),
        },
        events,
    )
    first = LLMPolicyCandidate(
        name="first",
        provider="fake",
        model="first-v1",
        contract_fingerprint="first-contract",
    )
    second = LLMPolicyCandidate(
        name="second",
        provider="fake",
        model="second-v1",
        contract_fingerprint="second-contract",
    )
    plan = LLMExperimentPlan(
        benchmark="holdout-hygiene",
        dataset="fixture",
        dataset_source="unit-test",
        candidates=(first, second),
        max_fallback_rate=1.0,
    )

    run_locked_shadow_benchmark(
        plan=plan,
        entries=(
            ShadowPlannerEntry(first, _RecordingPlanner("first", events)),
            ShadowPlannerEntry(second, _RecordingPlanner("second", events)),
        ),
        producer=producer,
        validation_specs=(validation,),
        holdout_specs=(holdout,),
        commit_sha="deadbeef",
    )

    holdout_evidence_index = events.index("evidence:holdout")
    first_validation_call = events.index("planner:first")
    second_validation_call = events.index("planner:second")
    assert holdout_evidence_index > first_validation_call
    assert holdout_evidence_index > second_validation_call
