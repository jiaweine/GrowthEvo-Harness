from __future__ import annotations

from dataclasses import dataclass

from growthevo.models import CausalBelief, GrowthGoal, GrowthOption


@dataclass(frozen=True, slots=True)
class GrowthHypothesis:
    option: GrowthOption
    rationale: str
    target_metric: str
    exploration_priority: float = 0.0


class GrowthHypothesisPlanner:
    """Reference semantic planner.

    The planner chooses *what growth problem to solve*. It intentionally does
    not choose channel, offer or budget; those are delegated to the numeric
    policy layer so an LLM planner cannot bypass policy constraints.
    """

    def plan(self, belief: CausalBelief, goal: GrowthGoal) -> GrowthHypothesis:
        if belief.fatigue >= goal.constraints.max_fatigue:
            return GrowthHypothesis(
                option=GrowthOption.HOLDOUT,
                rationale="User fatigue is at the configured ceiling; preserve a holdout action.",
                target_metric=goal.metric,
            )

        if belief.days_since_last_active >= 30 or belief.lifecycle_stage.lower() in {
            "dormant",
            "churned",
        }:
            return GrowthHypothesis(
                option=GrowthOption.REACTIVATE,
                rationale="Long inactivity suggests a reactivation objective.",
                target_metric=goal.metric,
            )

        if belief.lifecycle_stage.lower() in {"new", "onboarding"}:
            return GrowthHypothesis(
                option=GrowthOption.ACTIVATE,
                rationale="Early lifecycle state suggests activation before monetization.",
                target_metric=goal.metric,
            )

        if belief.churn_risk >= 0.30:
            return GrowthHypothesis(
                option=GrowthOption.RETAIN,
                rationale="Elevated churn risk prioritizes retention over short-term conversion.",
                target_metric=goal.metric,
            )

        if belief.uplift_uncertainty >= 0.25:
            return GrowthHypothesis(
                option=GrowthOption.EXPLORE,
                rationale="Treatment-effect uncertainty is high enough to justify controlled exploration.",
                target_metric=goal.metric,
                exploration_priority=min(1.0, belief.uplift_uncertainty),
            )

        return GrowthHypothesis(
            option=GrowthOption.UPSELL,
            rationale="Stable active user; optimize incremental value rather than raw conversion.",
            target_metric=goal.metric,
        )
