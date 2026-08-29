from __future__ import annotations

import pytest

from growthevo.models import Channel
from growthevo.rl.safe_policy_improvement import (
    ActionValueEstimate,
    SafePolicyImprovementConfig,
    SupportAnchoredPolicyImprover,
)


def test_provided_calibrated_bounds_rank_final_policy_not_raw_point_estimate() -> None:
    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(
            bound_mode="provided",
            support_mode="explicit",
            max_total_variation=0.20,
        )
    )
    result = improver.improve(
        [
            ActionValueEstimate(
                Channel.NO_TREATMENT,
                value=0.0,
                value_uncertainty=0.0,
                behavior_probability=0.60,
                value_lower_bound=0.0,
            ),
            ActionValueEstimate(
                Channel.PUSH,
                value=10.0,
                value_uncertainty=0.01,
                behavior_probability=0.20,
                value_lower_bound=-1.0,
                support_eligible=True,
            ),
            ActionValueEstimate(
                Channel.EMAIL,
                value=2.0,
                value_uncertainty=100.0,
                behavior_probability=0.20,
                value_lower_bound=1.0,
                support_eligible=True,
            ),
        ]
    )

    assert result.changed is True
    assert result.selected_action is Channel.EMAIL
    assert result.pessimistic_candidate_value > result.pessimistic_baseline_value
    assert "per_action_candidate_selected" in result.reasons
    assert "gaussian_reference_bounds_used" not in result.reasons


def test_explicit_support_overrides_behavior_probability_as_evidence() -> None:
    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(
            bound_mode="provided",
            support_mode="explicit",
            max_total_variation=0.20,
        )
    )
    result = improver.improve(
        [
            ActionValueEstimate(
                Channel.NO_TREATMENT,
                0.0,
                0.0,
                0.40,
                value_lower_bound=0.0,
            ),
            ActionValueEstimate(
                Channel.PUSH,
                5.0,
                0.0,
                0.50,
                value_lower_bound=5.0,
                support_eligible=False,
            ),
            ActionValueEstimate(
                Channel.EMAIL,
                1.0,
                0.0,
                0.10,
                value_lower_bound=1.0,
                support_eligible=True,
            ),
        ]
    )

    assert result.selected_action is Channel.EMAIL
    assert result.probabilities[Channel.PUSH] <= pytest.approx(0.50)
    assert "unsupported_actions_anchored" in result.reasons


def test_missing_explicit_support_fails_closed_for_treatment_actions() -> None:
    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(
            bound_mode="provided",
            support_mode="explicit",
            max_total_variation=0.20,
        )
    )
    result = improver.improve(
        [
            ActionValueEstimate(
                Channel.NO_TREATMENT,
                0.0,
                0.0,
                0.60,
                value_lower_bound=0.0,
            ),
            ActionValueEstimate(
                Channel.PUSH,
                5.0,
                0.0,
                0.40,
                value_lower_bound=5.0,
            ),
        ]
    )

    assert result.changed is False
    assert result.probabilities[Channel.PUSH] == pytest.approx(0.40)
    assert "missing_action_support_treated_as_unsupported" in result.reasons


def test_per_action_feasibility_prefers_action_with_material_safe_update_mass() -> None:
    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(
            confidence_z=0.0,
            max_total_variation=0.20,
            min_pessimistic_improvement=0.0,
        )
    )
    result = improver.improve(
        [
            ActionValueEstimate(
                Channel.NO_TREATMENT,
                value=0.0,
                value_uncertainty=0.0,
                behavior_probability=0.80,
                expected_cost=0.0,
            ),
            ActionValueEstimate(
                Channel.PUSH,
                value=10.0,
                value_uncertainty=0.0,
                behavior_probability=0.10,
                expected_cost=100.0,
            ),
            ActionValueEstimate(
                Channel.EMAIL,
                value=2.0,
                value_uncertainty=0.0,
                behavior_probability=0.10,
                expected_cost=2.0,
            ),
        ],
        max_expected_cost=10.30,
    )

    assert result.selected_action is Channel.EMAIL
    assert result.probabilities[Channel.EMAIL] > 0.10
    assert result.pessimistic_candidate_value > result.pessimistic_baseline_value


def test_learned_proposal_is_support_anchored_before_feasibility_search() -> None:
    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(
            bound_mode="provided",
            support_mode="explicit",
            unsupported_action_mode="freeze",
            max_total_variation=0.30,
        )
    )
    result = improver.improve(
        [
            ActionValueEstimate(
                Channel.NO_TREATMENT,
                0.0,
                0.0,
                0.50,
                value_lower_bound=0.0,
            ),
            ActionValueEstimate(
                Channel.PUSH,
                4.0,
                0.0,
                0.30,
                value_lower_bound=4.0,
                support_eligible=False,
            ),
            ActionValueEstimate(
                Channel.EMAIL,
                2.0,
                0.0,
                0.20,
                value_lower_bound=2.0,
                support_eligible=True,
            ),
        ],
        proposal_probabilities={
            Channel.NO_TREATMENT: 0.10,
            Channel.PUSH: 0.70,
            Channel.EMAIL: 0.20,
        },
    )

    assert result.probabilities[Channel.PUSH] <= pytest.approx(0.30)
    assert "proposal_support_constraint_active" in result.reasons


def test_hard_cost_violation_still_falls_back_to_no_treatment() -> None:
    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(confidence_z=0.0)
    )
    result = improver.improve(
        [
            ActionValueEstimate(
                Channel.NO_TREATMENT,
                value=0.0,
                value_uncertainty=0.0,
                behavior_probability=0.10,
                expected_cost=0.0,
            ),
            ActionValueEstimate(
                Channel.PUSH,
                value=5.0,
                value_uncertainty=0.0,
                behavior_probability=0.90,
                expected_cost=10.0,
            ),
        ],
        max_expected_cost=1.0,
    )

    assert result.safe_fallback is True
    assert result.selected_action is Channel.NO_TREATMENT
    assert result.probabilities[Channel.NO_TREATMENT] == pytest.approx(1.0)
    assert result.probabilities[Channel.PUSH] == pytest.approx(0.0)