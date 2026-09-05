from __future__ import annotations

from dataclasses import dataclass

import pytest

from growthevo.bench.llm_evaluation import (
    CausalOptionEvidence,
    LLMBenchmarkCase,
    LLMDecision,
    LLMExperimentPlan,
    LLMPolicyCandidate,
    LockedLLMPolicyProtocol,
    collect_planner_decisions,
    evaluate_llm_candidate,
)
from growthevo.models import (
    Channel,
    GrowthConstraints,
    GrowthGoal,
    GrowthOption,
    UserObservation,
)
from growthevo.runtime.belief_state import build_causal_belief
from growthevo.runtime.planner import GrowthHypothesis


def _goal() -> GrowthGoal:
    return GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=GrowthConstraints(max_budget=100.0),
    )


def _belief(*, user_id: str, fatigue: float = 0.1):
    return build_causal_belief(
        UserObservation(
            user_id=user_id,
            natural_conversion=0.2,
            channel_uplift={Channel.PUSH: 0.08, Channel.EMAIL: 0.04},
            uplift_uncertainty=0.05,
            ltv=100.0,
            fatigue=fatigue,
            churn_risk=0.1,
            days_since_last_active=0,
            lifecycle_stage="active",
        )
    )


def _candidate(name: str) -> LLMPolicyCandidate:
    return LLMPolicyCandidate(
        name=name,
        provider="test",
        model=f"model-{name}-snapshot",
        contract_fingerprint=f"contract-{name}",
    )


def _case(
    case_id: str,
    *,
    baseline: GrowthOption = GrowthOption.UPSELL,
    retain_value: float = 0.30,
    retain_support: float = 1.0,
    retain_feasible: bool = True,
) -> LLMBenchmarkCase:
    return LLMBenchmarkCase(
        case_id=case_id,
        belief=_belief(user_id=f"user-{case_id}"),
        goal=_goal(),
        baseline_option=baseline,
        option_evidence={
            GrowthOption.HOLDOUT: CausalOptionEvidence(value=0.0),
            GrowthOption.UPSELL: CausalOptionEvidence(value=0.10, standard_error=0.01),
            GrowthOption.RETAIN: CausalOptionEvidence(
                value=retain_value,
                standard_error=0.01,
                feasible=retain_feasible,
                support_coverage=retain_support,
                effective_sample_ratio=0.8,
            ),
            GrowthOption.REACTIVATE: CausalOptionEvidence(value=0.16, standard_error=0.02),
            GrowthOption.STOP: CausalOptionEvidence(value=-0.05, feasible=False),
        },
    )


def _decision(
    candidate: str,
    case_id: str,
    option: GrowthOption | None,
    *,
    reason: str = "accepted",
    confidence: float | None = 0.9,
    trial: int = 0,
) -> LLMDecision:
    return LLMDecision(
        candidate_name=candidate,
        case_id=case_id,
        option=option,
        runtime_option=option,
        proposed_option=option,
        confidence=confidence,
        accepted=reason == "accepted",
        used_llm=True,
        reason=reason,
        latency_ms=10.0,
        trial=trial,
    )


def test_locked_llm_protocol_selects_by_causal_incremental_lcb() -> None:
    better = _candidate("better")
    baseline_like = _candidate("baseline-like")
    plan = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(baseline_like, better),
    )
    cases = (
        _case("v1", retain_value=0.30),
        _case("v2", retain_value=0.25),
    )
    decisions = (
        _decision("better", "v1", GrowthOption.RETAIN),
        _decision("better", "v2", GrowthOption.RETAIN),
        _decision("baseline-like", "v1", GrowthOption.UPSELL),
        _decision("baseline-like", "v2", GrowthOption.UPSELL),
    )

    protocol = LockedLLMPolicyProtocol(plan)
    winner = protocol.tune(cases, decisions)

    assert winner.name == "better"
    score_by_name = {score.candidate.name: score for score in protocol.validation_scores}
    assert score_by_name["better"].incremental_lcb > 0
    assert score_by_name["better"].mean_regret == pytest.approx(0.0)
    assert score_by_name["baseline-like"].mean_incremental_over_baseline == pytest.approx(0.0)

    holdout_case = _case("h1", retain_value=0.35)
    holdout = protocol.evaluate_once(
        (holdout_case,),
        (_decision("better", "h1", GrowthOption.RETAIN),),
    )
    artifact = protocol.artifact(holdout, commit_sha="deadbeef")

    assert holdout.score.incremental_lcb > 0
    assert artifact.selected_candidate == "better"
    assert artifact.promotion_eligible is True
    assert artifact.tuning_fingerprint != artifact.test_fingerprint
    assert artifact.experiment_plan_fingerprint == plan.fingerprint

    with pytest.raises(RuntimeError, match="already been revealed"):
        protocol.evaluate_once(
            (_case("h2"),),
            (_decision("better", "h2", GrowthOption.RETAIN),),
        )


def test_evidence_infeasible_semantic_choice_is_fail_closed_and_disqualified() -> None:
    candidate = _candidate("unsafe")
    plan = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(candidate,),
        max_evidence_violation_rate=0.0,
    )
    case = _case("v1")
    score = evaluate_llm_candidate(
        (case,),
        (_decision("unsafe", "v1", GrowthOption.STOP),),
        candidate,
        plan,
    )

    assert score.evidence_violation_rate == pytest.approx(1.0)
    assert score.mean_incremental_over_baseline == pytest.approx(0.0)
    assert score.eligible is False

    protocol = LockedLLMPolicyProtocol(plan)
    with pytest.raises(ValueError, match="no LLM candidate"):
        protocol.tune(
            (case,),
            (_decision("unsafe", "v1", GrowthOption.STOP),),
        )


def test_low_support_option_cannot_win_even_with_large_point_estimate() -> None:
    candidate = _candidate("unsupported")
    plan = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(candidate,),
        min_support_coverage=0.95,
    )
    case = _case("v1", retain_value=5.0, retain_support=0.50)
    score = evaluate_llm_candidate(
        (case,),
        (_decision("unsupported", "v1", GrowthOption.RETAIN),),
        candidate,
        plan,
    )

    assert score.evidence_violation_rate == pytest.approx(1.0)
    assert score.mean_incremental_over_baseline == pytest.approx(0.0)
    assert score.eligible is False


def test_baseline_hard_stop_is_a_non_negotiable_benchmark_gate() -> None:
    candidate = _candidate("override")
    plan = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(candidate,),
    )
    case = LLMBenchmarkCase(
        case_id="fatigue-stop",
        belief=_belief(user_id="fatigued", fatigue=0.9),
        goal=_goal(),
        baseline_option=GrowthOption.HOLDOUT,
        option_evidence={
            GrowthOption.HOLDOUT: CausalOptionEvidence(value=0.0),
            GrowthOption.RETAIN: CausalOptionEvidence(value=1.0),
        },
    )
    score = evaluate_llm_candidate(
        (case,),
        (_decision("override", "fatigue-stop", GrowthOption.RETAIN),),
        candidate,
        plan,
    )

    assert score.hard_stop_violation_rate == pytest.approx(1.0)
    assert score.eligible is False


def test_holdout_manifest_rejects_non_winner_peeking() -> None:
    winner = _candidate("winner")
    loser = _candidate("loser")
    plan = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(winner, loser),
    )
    validation = (_case("v1"), _case("v2"))
    protocol = LockedLLMPolicyProtocol(plan)
    selected = protocol.tune(
        validation,
        (
            _decision("winner", "v1", GrowthOption.RETAIN),
            _decision("winner", "v2", GrowthOption.RETAIN),
            _decision("loser", "v1", GrowthOption.UPSELL),
            _decision("loser", "v2", GrowthOption.UPSELL),
        ),
    )
    assert selected.name == "winner"

    with pytest.raises(ValueError, match="only the frozen validation winner"):
        protocol.evaluate_once(
            (_case("h1"),),
            (
                _decision("winner", "h1", GrowthOption.RETAIN),
                _decision("loser", "h1", GrowthOption.RETAIN),
            ),
        )


def test_validation_and_holdout_case_identity_must_be_disjoint() -> None:
    candidate = _candidate("only")
    plan = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(candidate,),
    )
    case = _case("same")
    protocol = LockedLLMPolicyProtocol(plan)
    protocol.tune(
        (case,),
        (_decision("only", "same", GrowthOption.RETAIN),),
    )

    with pytest.raises(ValueError, match="overlap"):
        protocol.evaluate_once(
            (case,),
            (_decision("only", "same", GrowthOption.RETAIN),),
        )


@dataclass
class _ShadowPlanner:
    calls: int = 0

    def plan(self, belief, goal):
        self.calls += 1
        return GrowthHypothesis(
            option=GrowthOption.UPSELL,
            rationale="runtime baseline",
            target_metric=goal.metric,
        )

    def audit_snapshot(self):
        return {
            "used_llm": True,
            "accepted": False,
            "reason": "shadow_only",
            "provider": "fake",
            "model": "fake-snapshot",
            "proposed_option": "retain",
            "returned_option": "upsell",
            "confidence": 0.88,
            "latency_ms": 12.5,
            "shadow_mode": True,
        }


def test_shadow_collection_scores_proposal_without_changing_runtime_option() -> None:
    planner = _ShadowPlanner()
    case = _case("shadow")

    decisions = collect_planner_decisions(
        candidate_name="shadow-candidate",
        planner=planner,
        cases=(case,),
    )

    assert planner.calls == 1
    assert len(decisions) == 1
    assert decisions[0].option is GrowthOption.RETAIN
    assert decisions[0].runtime_option is GrowthOption.UPSELL
    assert decisions[0].proposed_option is GrowthOption.RETAIN
    assert decisions[0].reason == "shadow_only"


def test_plan_fingerprint_changes_when_candidate_contract_changes() -> None:
    first = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(_candidate("a"),),
    )
    changed = LLMExperimentPlan(
        benchmark="llm-growth-policy",
        dataset="hidden-causal-cases",
        dataset_source="fixture:v1",
        candidates=(
            LLMPolicyCandidate(
                name="a",
                provider="test",
                model="model-a-snapshot",
                contract_fingerprint="different-contract",
            ),
        ),
    )

    assert first.fingerprint != changed.fingerprint
