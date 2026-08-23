from __future__ import annotations

from dataclasses import dataclass

from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthConstraints, GrowthOption
from growthevo.runtime.planner import GrowthHypothesis


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    min_incremental_value: float = 0.01
    exploration_bonus: float = 0.10
    base_channel_cost: float = 0.05
    max_action_budget_fraction: float = 0.05


class HierarchicalGrowthPolicy:
    """Reference option-conditioned policy.

    This is intentionally deterministic and lightweight. Its purpose is to
    establish the action contract and safe separation between semantic planning
    and numeric decision-making. A learned policy can replace this class later.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def select_action(
        self,
        belief: CausalBelief,
        hypothesis: GrowthHypothesis,
        constraints: GrowthConstraints,
    ) -> GrowthAction:
        if hypothesis.option in {GrowthOption.HOLDOUT, GrowthOption.STOP}:
            return GrowthAction.no_treatment(hypothesis.option)

        candidates: list[tuple[float, Channel, float]] = []
        for channel in belief.consented_channels:
            uplift = belief.uplift_for(channel)
            if uplift <= 0:
                continue
            incremental_value = uplift * belief.ltv
            exploration = (
                self.config.exploration_bonus * belief.uplift_uncertainty
                if hypothesis.option is GrowthOption.EXPLORE
                else 0.0
            )
            score = incremental_value + exploration - self.config.base_channel_cost
            candidates.append((score, channel, uplift))

        if not candidates:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)

        score, channel, uplift = max(candidates, key=lambda item: (item[0], item[2], item[1].value))
        if score < self.config.min_incremental_value:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)

        offer_value = self._offer_for(hypothesis.option, uplift, constraints)
        expected_incremental_revenue = uplift * belief.ltv
        action_budget_cap = constraints.max_budget * self.config.max_action_budget_fraction
        budget = min(
            max(0.0, self.config.base_channel_cost + 0.10 * offer_value),
            max(0.0, constraints.max_budget - belief.spend_to_date),
            max(0.0, action_budget_cap),
        )

        if budget <= 0:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)

        estimated_roi = expected_incremental_revenue / budget if budget else float("inf")
        if estimated_roi < constraints.min_roi:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)

        return GrowthAction(
            option=hypothesis.option,
            channel=channel,
            offer_value=offer_value,
            budget=budget,
            frequency_cost=1.0,
            expected_uplift=uplift,
            uncertainty=belief.uplift_uncertainty,
            creative_id=f"{hypothesis.option.value}-{channel.value}-default",
            send_hour=20 if channel in {Channel.PUSH, Channel.EMAIL} else None,
        )

    @staticmethod
    def _offer_for(option: GrowthOption, uplift: float, constraints: GrowthConstraints) -> float:
        if option is GrowthOption.REACTIVATE:
            raw = 4.0 + 20.0 * max(0.0, uplift)
        elif option is GrowthOption.RETAIN:
            raw = 2.0 + 10.0 * max(0.0, uplift)
        elif option is GrowthOption.ACTIVATE:
            raw = 1.0 + 8.0 * max(0.0, uplift)
        else:
            raw = 0.0
        return min(raw, constraints.max_offer_value)
