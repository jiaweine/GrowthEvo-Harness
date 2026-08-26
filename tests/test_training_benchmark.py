from __future__ import annotations

import pytest

from growthevo.bench import GrowthAgentBench
from growthevo.bench.synthetic import evaluate_cate, make_synthetic_growth_bandit
from growthevo.causal.dr_learner import CrossFittedDRLearner
from growthevo.causal.serving import CausalUpliftServingBridge
from growthevo.models import Channel, UserObservation
from growthevo.rl.safe_policy_improvement import (
    ActionValueEstimate,
    SafePolicyImprovementConfig,
    SupportAnchoredPolicyImprover,
)
from growthevo.training.trajectory import PlannerTransition, TrajectoryTrainerAdapter


def test_cross_fitted_dr_learner_recovers_heterogeneous_push_effect() -> None:
    samples = make_synthetic_growth_bandit(1200, seed=11, outcome_noise=0.015)
    train = samples[:900]
    test = samples[900:]
    model = CrossFittedDRLearner(n_folds=5, ridge=1e-3).fit(
        (sample.record for sample in train),
        treatment=Channel.PUSH,
    )

    result = evaluate_cate(model, test)

    assert result.rmse < 0.03
    assert abs(result.bias) < 0.02
    assert model.overlap_coverage > 0.95
    assert result.mean_support_score > 0.90


def test_cate_uncertainty_increases_outside_training_support() -> None:
    samples = make_synthetic_growth_bandit(600, seed=19)
    model = CrossFittedDRLearner(n_folds=4).fit(
        (sample.record for sample in samples),
        treatment=Channel.EMAIL,
    )

    in_support = model.predict((0.0, 0.0))
    extrapolated = model.predict((3.0, 3.0))

    assert extrapolated.extrapolation_distance > 0
    assert extrapolated.uncertainty > in_support.uncertainty
    assert extrapolated.support_score < in_support.support_score


def test_causal_serving_bridge_enriches_runtime_observation() -> None:
    bench = GrowthAgentBench.synthetic(900, seed=23, outcome_noise=0.01)
    push, _ = bench.fit_cate(treatment=Channel.PUSH)
    email, _ = bench.fit_cate(treatment=Channel.EMAIL)
    bridge = CausalUpliftServingBridge({Channel.PUSH: push, Channel.EMAIL: email})
    observation = UserObservation(
        user_id="serve-u1",
        natural_conversion=0.2,
        channel_uplift={Channel.PUSH: 0.0},
        uplift_uncertainty=1.0,
        ltv=100.0,
        consented_channels=frozenset({Channel.PUSH, Channel.EMAIL}),
    )

    enriched, prediction = bridge.enrich_observation(observation, (0.0, 0.0))

    assert enriched.channel_uplift[Channel.PUSH] == pytest.approx(0.08, abs=0.03)
    assert enriched.channel_uplift[Channel.EMAIL] == pytest.approx(0.045, abs=0.03)
    assert enriched.uplift_uncertainty == pytest.approx(prediction.aggregate_uncertainty)
    assert prediction.minimum_support > 0.90


def test_growth_agent_bench_reports_low_regret_for_learned_cate_policy() -> None:
    bench = GrowthAgentBench.synthetic(1200, seed=31, outcome_noise=0.015)
    push, push_metric = bench.fit_cate(treatment=Channel.PUSH)
    email, email_metric = bench.fit_cate(treatment=Channel.EMAIL)

    def policy(features: tuple[float, ...]) -> Channel:
        values = {
            Channel.NO_TREATMENT: 0.0,
            Channel.PUSH: push.predict(features).effect,
            Channel.EMAIL: email.predict(features).effect,
        }
        return max(values, key=lambda action: (values[action], action.value))

    result = bench.evaluate_policy(policy)

    assert push_metric.rmse < 0.03
    assert email_metric.rmse < 0.03
    assert result.regret < 0.015


def _policy_estimates() -> list[ActionValueEstimate]:
    return [
        ActionValueEstimate(
            action=Channel.NO_TREATMENT,
            value=0.10,
            value_uncertainty=0.01,
            behavior_probability=0.50,
            expected_cost=0.0,
        ),
        ActionValueEstimate(
            action=Channel.PUSH,
            value=0.30,
            value_uncertainty=0.02,
            behavior_probability=0.30,
            expected_cost=0.05,
            cost_uncertainty=0.005,
        ),
        ActionValueEstimate(
            action=Channel.EMAIL,
            value=0.35,
            value_uncertainty=0.08,
            behavior_probability=0.20,
            expected_cost=0.02,
            cost_uncertainty=0.002,
        ),
    ]


def test_support_anchored_policy_improvement_respects_tv_cap() -> None:
    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(max_total_variation=0.10)
    )

    result = improver.improve(_policy_estimates())

    assert result.changed
    assert result.selected_action is Channel.PUSH
    assert result.total_variation_distance == pytest.approx(0.10)
    assert sum(result.probabilities.values()) == pytest.approx(1.0)
    assert result.pessimistic_candidate_value > result.pessimistic_baseline_value
    assert "reference_pessimistic_proposal_used" in result.reasons


def test_support_anchored_policy_freezes_low_support_action_mass() -> None:
    rows = _policy_estimates()
    rows[-1] = ActionValueEstimate(
        action=Channel.EMAIL,
        value=10.0,
        value_uncertainty=0.0,
        behavior_probability=0.001,
        expected_cost=0.0,
    )
    rows[0] = ActionValueEstimate(
        action=Channel.NO_TREATMENT,
        value=0.10,
        value_uncertainty=0.01,
        behavior_probability=0.699,
    )

    result = SupportAnchoredPolicyImprover().improve(rows)

    assert result.selected_action is Channel.PUSH
    assert result.probabilities[Channel.EMAIL] == pytest.approx(0.001)
    assert "low_support_actions_anchored" in result.reasons


def test_support_anchored_policy_accepts_external_learned_distribution() -> None:
    rows = _policy_estimates()
    result = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(max_total_variation=0.50)
    ).improve(
        rows,
        proposal_probabilities={
            Channel.NO_TREATMENT: 0.20,
            Channel.PUSH: 0.70,
            Channel.EMAIL: 0.10,
        },
    )

    assert result.changed
    assert result.selected_action is Channel.PUSH
    assert result.probabilities[Channel.PUSH] > 0.30
    assert "reference_pessimistic_proposal_used" not in result.reasons
    assert result.pessimistic_candidate_value > result.pessimistic_baseline_value


def test_low_support_external_proposal_is_bootstrapped_to_behavior() -> None:
    rows = _policy_estimates()
    rows[-1] = ActionValueEstimate(
        action=Channel.EMAIL,
        value=5.0,
        value_uncertainty=0.0,
        behavior_probability=0.001,
        expected_cost=0.0,
    )
    rows[0] = ActionValueEstimate(
        action=Channel.NO_TREATMENT,
        value=0.10,
        value_uncertainty=0.01,
        behavior_probability=0.699,
    )

    result = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(max_total_variation=1.0)
    ).improve(
        rows,
        proposal_probabilities={
            Channel.NO_TREATMENT: 0.10,
            Channel.PUSH: 0.10,
            Channel.EMAIL: 0.80,
        },
    )

    assert result.probabilities[Channel.EMAIL] == pytest.approx(0.001)
    assert "proposal_support_constraint_active" in result.reasons


def test_no_increase_mode_can_remove_unsupported_behavior_mass() -> None:
    rows = _policy_estimates()
    rows[-1] = ActionValueEstimate(
        action=Channel.EMAIL,
        value=-1.0,
        value_uncertainty=0.0,
        behavior_probability=0.001,
        expected_cost=0.0,
    )
    rows[0] = ActionValueEstimate(
        action=Channel.NO_TREATMENT,
        value=0.10,
        value_uncertainty=0.01,
        behavior_probability=0.699,
    )

    result = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(
            max_total_variation=1.0,
            unsupported_action_mode="no_increase",
        )
    ).improve(
        rows,
        proposal_probabilities={
            Channel.NO_TREATMENT: 0.40,
            Channel.PUSH: 0.60,
            Channel.EMAIL: 0.0,
        },
    )

    assert result.changed
    assert result.probabilities[Channel.EMAIL] == pytest.approx(0.0)


def test_support_anchored_policy_uses_no_treatment_when_behavior_cost_is_unsafe() -> None:
    rows = [
        ActionValueEstimate(
            action=Channel.NO_TREATMENT,
            value=0.0,
            value_uncertainty=0.0,
            behavior_probability=0.10,
            expected_cost=0.0,
        ),
        ActionValueEstimate(
            action=Channel.PUSH,
            value=1.0,
            value_uncertainty=0.0,
            behavior_probability=0.90,
            expected_cost=2.0,
        ),
    ]

    result = SupportAnchoredPolicyImprover().improve(rows, max_expected_cost=1.0)

    assert result.safe_fallback
    assert result.selected_action is Channel.NO_TREATMENT
    assert result.probabilities[Channel.NO_TREATMENT] == pytest.approx(1.0)


def test_minimum_pessimistic_gain_is_enforced_after_tv_contraction() -> None:
    result = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(
            max_total_variation=0.01,
            min_pessimistic_improvement=0.01,
        )
    ).improve(_policy_estimates())

    assert result.changed is False
    assert "minimum_pessimistic_gain_not_reached" in result.reasons


def test_dynamics_boundary_stops_gae_credit_leakage() -> None:
    adapter = TrajectoryTrainerAdapter(
        gamma=1.0,
        gae_lambda=1.0,
        normalize_advantages=False,
    )
    no_boundary = adapter.build(
        [
            PlannerTransition(
                trajectory_id="t",
                step_index=0,
                action="inspect",
                observation={"evidence": 0.2},
                reward=0.0,
            ),
            PlannerTransition(
                trajectory_id="t",
                step_index=1,
                action="act",
                observation={"outcome": 1},
                reward=1.0,
                done=True,
            ),
        ]
    )
    with_boundary = adapter.build(
        [
            PlannerTransition(
                trajectory_id="t",
                step_index=0,
                action="inspect",
                observation={"evidence": 0.2},
                reward=0.0,
                credit_boundary=True,
            ),
            PlannerTransition(
                trajectory_id="t",
                step_index=1,
                action="act",
                observation={"outcome": 1},
                reward=1.0,
                done=True,
            ),
        ]
    )

    assert no_boundary.samples[0].raw_advantage == pytest.approx(1.0)
    assert with_boundary.samples[0].raw_advantage == pytest.approx(0.0)
    assert with_boundary.samples[1].raw_advantage == pytest.approx(1.0)


def test_training_adapter_exports_stable_jsonl() -> None:
    batch = TrajectoryTrainerAdapter(normalize_advantages=False).build(
        [
            PlannerTransition(
                trajectory_id="traj-1",
                step_index=0,
                action="query_uplift",
                observation={"support": 0.98},
                reward=0.3,
                done=True,
                legal_action=True,
                tool_success=True,
            )
        ]
    )

    payload = batch.to_jsonl()

    assert '"trajectory_id": "traj-1"' in payload
    assert '"legal_action": true' in payload
    assert '"support": 0.98' in payload
