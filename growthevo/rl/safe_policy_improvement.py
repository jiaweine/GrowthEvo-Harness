from __future__ import annotations

from dataclasses import dataclass
from math import fsum
from typing import Iterable, Mapping

from growthevo.models import Channel


@dataclass(frozen=True, slots=True)
class ActionValueEstimate:
    """Pessimistic inputs for one discrete growth action.

    ``value_uncertainty`` and ``cost_uncertainty`` are estimator diagnostics
    supplied by the caller. They are converted into lower/upper bounds by the
    policy improver; they are not assumed to be calibrated unless the caller has
    calibrated them upstream.
    """

    action: Channel
    value: float
    value_uncertainty: float
    behavior_probability: float
    expected_cost: float = 0.0
    cost_uncertainty: float = 0.0

    def __post_init__(self) -> None:
        if self.value_uncertainty < 0 or self.cost_uncertainty < 0:
            raise ValueError("uncertainty values must be non-negative")
        if not 0 <= self.behavior_probability <= 1:
            raise ValueError("behavior_probability must be in [0, 1]")
        if self.expected_cost < 0:
            raise ValueError("expected_cost must be non-negative")


@dataclass(frozen=True, slots=True)
class SafePolicyImprovementConfig:
    confidence_z: float = 1.96
    support_floor: float = 0.02
    max_total_variation: float = 0.20
    min_pessimistic_improvement: float = 0.0

    def __post_init__(self) -> None:
        if self.confidence_z < 0:
            raise ValueError("confidence_z must be non-negative")
        if not 0 < self.support_floor <= 1:
            raise ValueError("support_floor must be in (0, 1]")
        if not 0 <= self.max_total_variation <= 1:
            raise ValueError("max_total_variation must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class PolicyImprovementResult:
    probabilities: Mapping[Channel, float]
    selected_action: Channel
    pessimistic_baseline_value: float
    pessimistic_candidate_value: float
    expected_cost_ucb: float
    total_variation_distance: float
    changed: bool
    safe_fallback: bool = False
    reasons: tuple[str, ...] = ()


class SupportAnchoredPolicyImprover:
    """Conservative one-step policy improvement anchored to logged behavior.

    The new policy is a bounded mixture between the behavior policy and a
    pessimistically selected supported action. This prevents a contextual growth
    policy from jumping directly to an out-of-support action merely because a
    value model extrapolates optimistically.

    This module is intentionally a *safe improvement kernel*, not a theorem that
    arbitrary learned uncertainty is calibrated. Deployment still requires OPE,
    overlap diagnostics and the Counterfactual Verifier.
    """

    def __init__(self, config: SafePolicyImprovementConfig | None = None) -> None:
        self.config = config or SafePolicyImprovementConfig()

    def improve(
        self,
        estimates: Iterable[ActionValueEstimate],
        *,
        max_expected_cost: float | None = None,
    ) -> PolicyImprovementResult:
        rows = list(estimates)
        if not rows:
            raise ValueError("at least one action estimate is required")
        if len({row.action for row in rows}) != len(rows):
            raise ValueError("action estimates must be unique by action")
        if Channel.NO_TREATMENT not in {row.action for row in rows}:
            raise ValueError("NO_TREATMENT estimate is required as a safe fallback")
        behavior_total = fsum(row.behavior_probability for row in rows)
        if abs(behavior_total - 1.0) > 1e-6:
            raise ValueError("behavior probabilities must sum to 1")
        if max_expected_cost is not None and max_expected_cost < 0:
            raise ValueError("max_expected_cost must be non-negative")

        cfg = self.config
        value_lcb = {
            row.action: row.value - cfg.confidence_z * row.value_uncertainty for row in rows
        }
        cost_ucb = {
            row.action: row.expected_cost + cfg.confidence_z * row.cost_uncertainty
            for row in rows
        }
        behavior = {row.action: row.behavior_probability for row in rows}
        baseline_value = fsum(behavior[row.action] * value_lcb[row.action] for row in rows)
        baseline_cost = fsum(behavior[row.action] * cost_ucb[row.action] for row in rows)

        if max_expected_cost is not None and baseline_cost > max_expected_cost:
            fallback = {row.action: 0.0 for row in rows}
            fallback[Channel.NO_TREATMENT] = 1.0
            return PolicyImprovementResult(
                probabilities=fallback,
                selected_action=Channel.NO_TREATMENT,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=value_lcb[Channel.NO_TREATMENT],
                expected_cost_ucb=cost_ucb[Channel.NO_TREATMENT],
                total_variation_distance=1.0 - behavior[Channel.NO_TREATMENT],
                changed=True,
                safe_fallback=True,
                reasons=("behavior_policy_cost_above_hard_limit",),
            )

        supported = [
            row
            for row in rows
            if row.action is Channel.NO_TREATMENT
            or row.behavior_probability >= cfg.support_floor
        ]
        unsupported_count = len(rows) - len(supported)
        selected = max(supported, key=lambda row: (value_lcb[row.action], row.action.value))
        selected_lcb = value_lcb[selected.action]

        base_reasons: list[str] = []
        if unsupported_count:
            base_reasons.append("unsupported_actions_excluded")
        if selected_lcb <= baseline_value + cfg.min_pessimistic_improvement:
            return PolicyImprovementResult(
                probabilities=behavior,
                selected_action=selected.action,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=baseline_value,
                expected_cost_ucb=baseline_cost,
                total_variation_distance=0.0,
                changed=False,
                reasons=tuple(base_reasons + ["no_pessimistic_improvement"]),
            )

        selected_behavior = behavior[selected.action]
        tv_per_unit_mix = max(1e-15, 1.0 - selected_behavior)
        mixture = min(1.0, cfg.max_total_variation / tv_per_unit_mix)
        reasons = base_reasons + ["pessimistic_supported_action_selected"]
        if mixture < 1.0:
            reasons.append("total_variation_cap_active")

        if max_expected_cost is not None:
            selected_cost = cost_ucb[selected.action]
            if selected_cost > baseline_cost:
                allowed_mix = (max_expected_cost - baseline_cost) / (selected_cost - baseline_cost)
                allowed_mix = max(0.0, min(1.0, allowed_mix))
                if allowed_mix < mixture:
                    mixture = allowed_mix
                    reasons.append("expected_cost_cap_active")

        if mixture <= 1e-12:
            return PolicyImprovementResult(
                probabilities=behavior,
                selected_action=selected.action,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=baseline_value,
                expected_cost_ucb=baseline_cost,
                total_variation_distance=0.0,
                changed=False,
                reasons=tuple(reasons + ["safe_update_mass_is_zero"]),
            )

        candidate = {
            action: (1.0 - mixture) * probability for action, probability in behavior.items()
        }
        candidate[selected.action] += mixture
        candidate_value = (1.0 - mixture) * baseline_value + mixture * selected_lcb
        candidate_cost = (1.0 - mixture) * baseline_cost + mixture * cost_ucb[selected.action]
        total_variation = mixture * (1.0 - selected_behavior)

        return PolicyImprovementResult(
            probabilities=candidate,
            selected_action=selected.action,
            pessimistic_baseline_value=baseline_value,
            pessimistic_candidate_value=candidate_value,
            expected_cost_ucb=candidate_cost,
            total_variation_distance=total_variation,
            changed=True,
            reasons=tuple(reasons),
        )
