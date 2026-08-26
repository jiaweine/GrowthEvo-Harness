from __future__ import annotations

from dataclasses import dataclass

import pytest

from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthConstraints, GrowthOption
from growthevo.rl.hierarchical_policy import HierarchicalGrowthPolicy, PolicyConfig
from growthevo.runtime.planner import GrowthHypothesis


def _belief() -> CausalBelief:
    return CausalBelief(
        user_id="policy-user",
        natural_conversion=0.2,
        channel_uplift={Channel.PUSH: 0.10, Channel.EMAIL: 0.08},
        uplift_uncertainty=0.5,
        ltv=100.0,
        fatigue=0.1,
        churn_risk=0.1,
        touches_24h=0,
        touches_7d=0,
        spend_to_date=0.0,
        days_since_last_active=5,
        lifecycle_stage="active",
        consented_channels=frozenset({Channel.PUSH, Channel.EMAIL}),
        channel_uncertainty={Channel.PUSH: 0.20, Channel.EMAIL: 0.01},
        channel_support={Channel.PUSH: 0.95, Channel.EMAIL: 0.95},
    )


def _constraints() -> GrowthConstraints:
    return GrowthConstraints(max_budget=10.0, min_roi=1.0)


def _hypothesis() -> GrowthHypothesis:
    return GrowthHypothesis(
        option=GrowthOption.ACTIVATE,
        rationale="test",
        target_metric="incremental_ltv",
    )


def test_policy_uses_channel_specific_uncertainty_not_global_maximum() -> None:
    action = HierarchicalGrowthPolicy().select_action(
        _belief(),
        _hypothesis(),
        _constraints(),
    )

    assert action.channel is Channel.EMAIL
    assert action.uncertainty == pytest.approx(0.01)


def test_policy_refuses_low_support_channel_even_when_nominal_uplift_is_high() -> None:
    belief = _belief()
    low_support = CausalBelief(
        user_id=belief.user_id,
        natural_conversion=belief.natural_conversion,
        channel_uplift={Channel.PUSH: 0.9, Channel.EMAIL: 0.08},
        uplift_uncertainty=belief.uplift_uncertainty,
        ltv=belief.ltv,
        fatigue=belief.fatigue,
        churn_risk=belief.churn_risk,
        touches_24h=belief.touches_24h,
        touches_7d=belief.touches_7d,
        spend_to_date=belief.spend_to_date,
        days_since_last_active=belief.days_since_last_active,
        lifecycle_stage=belief.lifecycle_stage,
        consented_channels=belief.consented_channels,
        channel_uncertainty={Channel.PUSH: 0.01, Channel.EMAIL: 0.01},
        channel_support={Channel.PUSH: 0.001, Channel.EMAIL: 0.95},
    )

    action = HierarchicalGrowthPolicy(
        PolicyConfig(min_channel_support=0.02)
    ).select_action(low_support, _hypothesis(), _constraints())

    assert action.channel is Channel.EMAIL


def test_reference_policy_has_no_hidden_offer_schedule_or_creative_rule() -> None:
    action = HierarchicalGrowthPolicy().select_action(
        _belief(),
        _hypothesis(),
        _constraints(),
    )

    assert action.offer_value == pytest.approx(0.0)
    assert action.send_hour is None
    assert action.creative_id is None


@dataclass
class CampaignParameterizer:
    def expected_cost(self, belief, hypothesis, channel, constraints) -> float:
        del belief, hypothesis, constraints
        return 0.2 if channel is Channel.EMAIL else 0.4

    def build_action(
        self,
        belief,
        hypothesis,
        channel,
        *,
        expected_uplift,
        uncertainty,
        constraints,
    ) -> GrowthAction:
        del belief, constraints
        return GrowthAction(
            option=hypothesis.option,
            channel=channel,
            offer_value=3.0,
            budget=self.expected_cost(None, None, channel, None),
            frequency_cost=0.5,
            expected_uplift=expected_uplift,
            uncertainty=uncertainty,
            creative_id="campaign-creative",
            send_hour=9,
        )


def test_business_action_parameters_can_be_injected_without_editing_policy() -> None:
    action = HierarchicalGrowthPolicy(
        action_parameterizer=CampaignParameterizer()
    ).select_action(_belief(), _hypothesis(), _constraints())

    assert action.channel is Channel.EMAIL
    assert action.offer_value == pytest.approx(3.0)
    assert action.budget == pytest.approx(0.2)
    assert action.frequency_cost == pytest.approx(0.5)
    assert action.creative_id == "campaign-creative"
    assert action.send_hour == 9
