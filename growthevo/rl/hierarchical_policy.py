from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthConstraints, GrowthOption
from growthevo.runtime.planner import GrowthHypothesis


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    """Decision-level controls for the reference hierarchical policy."""

    min_incremental_value: float = 0.01
    uncertainty_penalty: float = 1.0
    exploration_uncertainty_weight: float = 0.25
    min_channel_support: float = 0.02

    def __post_init__(self) -> None:
        if self.min_incremental_value < 0:
            raise ValueError("min_incremental_value must be non-negative")
        if self.uncertainty_penalty < 0:
            raise ValueError("uncertainty_penalty must be non-negative")
        if self.exploration_uncertainty_weight < 0:
            raise ValueError("exploration_uncertainty_weight must be non-negative")
        if not 0 <= self.min_channel_support <= 1:
            raise ValueError("min_channel_support must be in [0, 1]")


class ActionParameterizer(Protocol):
    """Business-specific action construction kept outside policy scoring."""

    def expected_cost(
        self,
        belief: CausalBelief,
        hypothesis: GrowthHypothesis,
        channel: Channel,
        constraints: GrowthConstraints,
    ) -> float: ...

    def build_action(
        self,
        belief: CausalBelief,
        hypothesis: GrowthHypothesis,
        channel: Channel,
        *,
        expected_uplift: float,
        uncertainty: float,
        constraints: GrowthConstraints,
    ) -> GrowthAction | None: ...


@dataclass(frozen=True, slots=True)
class ReferenceActionParameterizer:
    """Minimal channel-agnostic parameterizer used by demos and tests.

    Production systems should replace this with a campaign catalog, auction cost
    model, offer optimizer, or scheduling policy. The reference implementation
    intentionally contains no channel-specific send time or option-specific offer
    formula.
    """

    direct_cost: float = 0.05
    max_budget_fraction: float = 0.05
    frequency_cost: float = 1.0

    def __post_init__(self) -> None:
        if self.direct_cost < 0:
            raise ValueError("direct_cost must be non-negative")
        if not 0 <= self.max_budget_fraction <= 1:
            raise ValueError("max_budget_fraction must be in [0, 1]")
        if self.frequency_cost < 0:
            raise ValueError("frequency_cost must be non-negative")

    def _budget(self, belief: CausalBelief, constraints: GrowthConstraints) -> float:
        remaining = max(0.0, constraints.max_budget - belief.spend_to_date)
        per_action_cap = max(0.0, constraints.max_budget * self.max_budget_fraction)
        return min(self.direct_cost, remaining, per_action_cap)

    def expected_cost(
        self,
        belief: CausalBelief,
        hypothesis: GrowthHypothesis,
        channel: Channel,
        constraints: GrowthConstraints,
    ) -> float:
        del hypothesis, channel
        return self._budget(belief, constraints)

    def build_action(
        self,
        belief: CausalBelief,
        hypothesis: GrowthHypothesis,
        channel: Channel,
        *,
        expected_uplift: float,
        uncertainty: float,
        constraints: GrowthConstraints,
    ) -> GrowthAction | None:
        budget = self._budget(belief, constraints)
        if budget <= 0:
            return None
        return GrowthAction(
            option=hypothesis.option,
            channel=channel,
            budget=budget,
            frequency_cost=self.frequency_cost,
            expected_uplift=expected_uplift,
            uncertainty=uncertainty,
        )


class HierarchicalGrowthPolicy:
    """Option-conditioned conservative channel policy.

    The policy chooses *which causal action* is worth considering. Offer value,
    creative, schedule, and auction/campaign costs belong to an injected action
    parameterizer. This prevents business heuristics from becoming hidden parts
    of the learning algorithm.
    """

    def __init__(
        self,
        config: PolicyConfig | None = None,
        *,
        action_parameterizer: ActionParameterizer | None = None,
    ) -> None:
        self.config = config or PolicyConfig()
        self.action_parameterizer = action_parameterizer or ReferenceActionParameterizer()

    def select_action(
        self,
        belief: CausalBelief,
        hypothesis: GrowthHypothesis,
        constraints: GrowthConstraints,
    ) -> GrowthAction:
        if hypothesis.option in {GrowthOption.HOLDOUT, GrowthOption.STOP}:
            return GrowthAction.no_treatment(hypothesis.option)

        cfg = self.config
        candidates: list[tuple[float, float, Channel, float, float]] = []
        for channel in belief.consented_channels:
            support = belief.support_for(channel)
            if support < cfg.min_channel_support:
                continue
            uplift = belief.uplift_for(channel)
            uncertainty = belief.uncertainty_for(channel)
            conservative_uplift = uplift - cfg.uncertainty_penalty * uncertainty
            if hypothesis.option is GrowthOption.EXPLORE:
                conservative_uplift += cfg.exploration_uncertainty_weight * uncertainty * support
            if conservative_uplift <= 0:
                continue

            expected_cost = self.action_parameterizer.expected_cost(
                belief,
                hypothesis,
                channel,
                constraints,
            )
            if expected_cost < 0:
                raise ValueError("action parameterizer returned negative expected cost")
            conservative_value = conservative_uplift * belief.ltv - expected_cost
            candidates.append(
                (conservative_value, support, channel, uplift, uncertainty)
            )

        if not candidates:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)

        score, _, channel, uplift, uncertainty = max(
            candidates,
            key=lambda item: (item[0], item[1], item[2].value),
        )
        if score < cfg.min_incremental_value:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)

        action = self.action_parameterizer.build_action(
            belief,
            hypothesis,
            channel,
            expected_uplift=uplift,
            uncertainty=uncertainty,
            constraints=constraints,
        )
        if action is None:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)
        if action.channel is not channel:
            raise ValueError("action parameterizer changed the selected channel")
        if action.option is not hypothesis.option:
            raise ValueError("action parameterizer changed the selected growth option")

        conservative_uplift = uplift - cfg.uncertainty_penalty * uncertainty
        if hypothesis.option is GrowthOption.EXPLORE:
            conservative_uplift += cfg.exploration_uncertainty_weight * uncertainty * belief.support_for(channel)
        conservative_revenue = max(0.0, conservative_uplift) * belief.ltv
        if action.budget <= 0:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)
        estimated_roi = conservative_revenue / action.budget
        if estimated_roi < constraints.min_roi:
            return GrowthAction.no_treatment(GrowthOption.HOLDOUT)

        return action
