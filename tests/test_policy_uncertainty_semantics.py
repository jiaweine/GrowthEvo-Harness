from __future__ import annotations

from growthevo.models import CausalBelief, Channel, GrowthConstraints, GrowthOption
from growthevo.rl.hierarchical_policy import HierarchicalGrowthPolicy, PolicyConfig
from growthevo.runtime.planner import GrowthHypothesis


def _belief(
    *,
    ltv: float = 100.0,
    lower_bounds: dict[Channel, float] | None = None,
) -> CausalBelief:
    return CausalBelief(
        user_id="u",
        natural_conversion=0.1,
        channel_uplift={Channel.PUSH: 0.20, Channel.EMAIL: 0.12},
        uplift_uncertainty=0.15,
        ltv=ltv,
        fatigue=0.0,
        churn_risk=0.0,
        touches_24h=0,
        touches_7d=0,
        spend_to_date=0.0,
        days_since_last_active=10,
        lifecycle_stage="active",
        consented_channels=frozenset({Channel.PUSH, Channel.EMAIL}),
        channel_uncertainty={Channel.PUSH: 0.15, Channel.EMAIL: 0.01},
        channel_support={Channel.PUSH: 1.0, Channel.EMAIL: 1.0},
        channel_effect_lower_bound=lower_bounds or {},
    )


def _constraints(*, min_roi: float = 1.0) -> GrowthConstraints:
    return GrowthConstraints(
        max_budget=100.0,
        min_roi=min_roi,
        max_fatigue=1.0,
        max_churn_risk=1.0,
        max_touches_24h=10,
        max_touches_7d=20,
    )


def test_policy_prefers_explicit_effect_lower_bound_over_uncalibrated_residual_penalty() -> None:
    hypothesis = GrowthHypothesis(
        option=GrowthOption.REACTIVATE,
        rationale="test",
        target_metric="incremental_ltv",
    )
    policy = HierarchicalGrowthPolicy()

    without_bound = policy.select_action(_belief(), hypothesis, _constraints())
    with_bound = policy.select_action(
        _belief(lower_bounds={Channel.PUSH: 0.18}),
        hypothesis,
        _constraints(),
    )

    assert without_bound.channel is Channel.EMAIL
    assert with_bound.channel is Channel.PUSH


def test_exploration_bonus_cannot_manufacture_roi_evidence() -> None:
    belief = CausalBelief(
        user_id="explore-u",
        natural_conversion=0.1,
        channel_uplift={Channel.PUSH: 0.06},
        uplift_uncertainty=0.04,
        ltv=1.0,
        fatigue=0.0,
        churn_risk=0.0,
        touches_24h=0,
        touches_7d=0,
        spend_to_date=0.0,
        days_since_last_active=1,
        lifecycle_stage="active",
        consented_channels=frozenset({Channel.PUSH}),
        channel_uncertainty={Channel.PUSH: 0.04},
        channel_support={Channel.PUSH: 1.0},
    )
    hypothesis = GrowthHypothesis(
        option=GrowthOption.EXPLORE,
        rationale="test",
        target_metric="incremental_ltv",
    )
    policy = HierarchicalGrowthPolicy(
        PolicyConfig(
            min_incremental_value=0.0,
            uncertainty_penalty=1.0,
            exploration_uncertainty_weight=10.0,
            min_channel_support=0.0,
        )
    )

    action = policy.select_action(belief, hypothesis, _constraints(min_roi=1.0))

    # Ranking sees the exploration bonus, but ROI uses only the conservative
    # safety uplift: (0.06 - 0.04) * 1.0 / 0.05 = 0.4 < 1.0.
    assert action.channel is Channel.NO_TREATMENT
