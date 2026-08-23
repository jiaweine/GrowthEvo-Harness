from __future__ import annotations

import pytest

from growthevo.bench.synthetic import evaluate_cate, make_synthetic_growth_bandit
from growthevo.causal.dr_learner import CrossFittedDRLearner
from growthevo.models import Channel
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


def test_support_anchored_policy_excludes_unsupported_optimistic_action() -> None:
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
    assert "unsupported_actions_excluded" in result.reasons


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
