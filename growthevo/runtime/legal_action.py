from __future__ import annotations

from dataclasses import dataclass

from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthConstraints


@dataclass(frozen=True, slots=True)
class ActionDecision:
    allowed: bool
    reasons: tuple[str, ...] = ()


class LegalActionGate:
    """Apply non-learnable user, budget and fatigue constraints before execution."""

    def evaluate(
        self,
        belief: CausalBelief,
        action: GrowthAction,
        constraints: GrowthConstraints,
    ) -> ActionDecision:
        if action.channel is Channel.NO_TREATMENT:
            return ActionDecision(allowed=True)

        reasons: list[str] = []

        if action.channel not in belief.consented_channels:
            reasons.append(f"channel_not_consented:{action.channel.value}")
        if belief.spend_to_date + action.budget > constraints.max_budget:
            reasons.append("budget_exceeded")
        if action.offer_value > constraints.max_offer_value:
            reasons.append("offer_cap_exceeded")
        if belief.fatigue >= constraints.max_fatigue:
            reasons.append("fatigue_limit_reached")
        if belief.churn_risk >= constraints.max_churn_risk:
            reasons.append("churn_risk_limit_reached")
        if belief.touches_24h >= constraints.max_touches_24h:
            reasons.append("touch_24h_limit_reached")
        if belief.touches_7d >= constraints.max_touches_7d:
            reasons.append("touch_7d_limit_reached")

        return ActionDecision(allowed=not reasons, reasons=tuple(reasons))
