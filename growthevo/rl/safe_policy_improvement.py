from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite
from typing import Iterable, Literal, Mapping

from growthevo.models import Channel


@dataclass(frozen=True, slots=True)
class ActionValueEstimate:
    """Inputs for one discrete action plus optional calibrated bounds.

    ``behavior_probability`` defines the baseline policy distribution; it is not
    used as a proxy for statistical support. ``support_eligible`` is supplied by
    the upstream evidence protocol and may reflect local overlap, sample counts,
    effective sample size, confidence sets, or another defensible criterion.
    Missing treatment support fails closed and is treated as unsupported.

    ``value_uncertainty`` and ``cost_uncertainty`` remain model diagnostics. They
    are converted to Gaussian-style bounds only when the experiment explicitly
    opts into ``gaussian_reference`` mode. The default safety path consumes
    caller-provided lower/upper bounds instead of inventing statistical meaning
    for an arbitrary uncertainty score.
    """

    action: Channel
    value: float
    value_uncertainty: float
    behavior_probability: float
    expected_cost: float = 0.0
    cost_uncertainty: float = 0.0
    value_lower_bound: float | None = None
    cost_upper_bound: float | None = None
    support_eligible: bool | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("value", self.value),
            ("value_uncertainty", self.value_uncertainty),
            ("behavior_probability", self.behavior_probability),
            ("expected_cost", self.expected_cost),
            ("cost_uncertainty", self.cost_uncertainty),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.value_uncertainty < 0 or self.cost_uncertainty < 0:
            raise ValueError("uncertainty values must be non-negative")
        if not 0 <= self.behavior_probability <= 1:
            raise ValueError("behavior_probability must be in [0, 1]")
        if self.expected_cost < 0:
            raise ValueError("expected_cost must be non-negative")
        if self.value_lower_bound is not None:
            if not isfinite(self.value_lower_bound):
                raise ValueError("value_lower_bound must be finite")
            if self.value_lower_bound > self.value + 1e-12:
                raise ValueError("value_lower_bound cannot exceed the point estimate")
        if self.cost_upper_bound is not None:
            if not isfinite(self.cost_upper_bound) or self.cost_upper_bound < 0:
                raise ValueError("cost_upper_bound must be finite and non-negative")
            if self.cost_upper_bound + 1e-12 < self.expected_cost:
                raise ValueError("cost_upper_bound cannot be below the point estimate")
        if self.action is Channel.NO_TREATMENT:
            if self.expected_cost != 0.0:
                raise ValueError("NO_TREATMENT expected_cost must be zero")
            if self.cost_upper_bound not in {None, 0.0}:
                raise ValueError("NO_TREATMENT cost_upper_bound must be zero when provided")


@dataclass(frozen=True, slots=True)
class SafePolicyImprovementConfig:
    """Explicit trust-region and bound semantics for policy improvement.

    ``max_total_variation`` is intentionally required: the library does not
    choose how far a learned policy may move from the logging policy. Statistical
    support is not configured here because it belongs to the upstream evidence
    protocol and arrives per action through ``support_eligible``.
    """

    max_total_variation: float
    min_pessimistic_improvement: float = 0.0
    unsupported_action_mode: Literal["freeze", "no_increase"] = "freeze"
    bound_mode: Literal["provided", "gaussian_reference"] = "provided"
    confidence_z: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.max_total_variation) or not 0 <= self.max_total_variation <= 1:
            raise ValueError("max_total_variation must be a finite value in [0, 1]")
        if (
            not isfinite(self.min_pessimistic_improvement)
            or self.min_pessimistic_improvement < 0
        ):
            raise ValueError("min_pessimistic_improvement must be non-negative and finite")
        if self.unsupported_action_mode not in {"freeze", "no_increase"}:
            raise ValueError("unsupported_action_mode must be freeze or no_increase")
        if self.bound_mode not in {"provided", "gaussian_reference"}:
            raise ValueError("bound_mode must be provided or gaussian_reference")
        if self.bound_mode == "gaussian_reference":
            if self.confidence_z is None:
                raise ValueError("gaussian_reference mode requires an explicit confidence_z")
            if self.confidence_z < 0 or not isfinite(self.confidence_z):
                raise ValueError("confidence_z must be a non-negative finite value")
        elif self.confidence_z is not None:
            raise ValueError("confidence_z is only used in gaussian_reference mode")


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
    """Contract an arbitrary learned proposal toward the logging policy.

    This is a support-anchoring kernel, not a theorem generator. In default
    ``provided`` mode, upstream evaluation must supply action-value lower bounds
    and, when a hard expected-cost cap is requested, cost upper bounds. The
    optional ``gaussian_reference`` mode exists for controlled experiments but
    must be selected explicitly because model uncertainty is not automatically a
    calibrated confidence interval.

    The constructor accepts ``None`` only so wiring code can instantiate the
    component before a deployment protocol is available. ``improve`` then fails
    closed until an explicit ``SafePolicyImprovementConfig`` is supplied.
    """

    def __init__(self, config: SafePolicyImprovementConfig | None = None) -> None:
        self.config = config

    def _require_config(self) -> SafePolicyImprovementConfig:
        if self.config is None:
            raise ValueError(
                "safe policy improvement protocol is not configured; "
                "provide an explicit max_total_variation and bound semantics"
            )
        return self.config

    @staticmethod
    def _validate_distribution(
        probabilities: Mapping[Channel, float],
        actions: tuple[Channel, ...],
        *,
        name: str,
    ) -> dict[Channel, float]:
        unknown = set(probabilities).difference(actions)
        if unknown:
            raise ValueError(
                f"{name} contains unknown actions: "
                f"{sorted(action.value for action in unknown)}"
            )
        result = {action: float(probabilities.get(action, 0.0)) for action in actions}
        if any(not isfinite(probability) for probability in result.values()):
            raise ValueError(f"{name} probabilities must be finite")
        if any(probability < 0.0 or probability > 1.0 for probability in result.values()):
            raise ValueError(f"{name} probabilities must be in [0, 1]")
        if abs(fsum(result.values()) - 1.0) > 1e-6:
            raise ValueError(f"{name} probabilities must sum to 1")
        return result

    def _value_bounds(
        self,
        rows: list[ActionValueEstimate],
        cfg: SafePolicyImprovementConfig,
    ) -> dict[Channel, float]:
        if cfg.bound_mode == "gaussian_reference":
            assert cfg.confidence_z is not None
            return {
                row.action: row.value - cfg.confidence_z * row.value_uncertainty
                for row in rows
            }
        missing = [row.action.value for row in rows if row.value_lower_bound is None]
        if missing:
            raise ValueError(
                "provided bound mode requires value_lower_bound for every action; "
                f"missing={sorted(missing)}"
            )
        return {
            row.action: float(row.value_lower_bound)
            for row in rows
            if row.value_lower_bound is not None
        }

    def _cost_bounds(
        self,
        rows: list[ActionValueEstimate],
        *,
        cfg: SafePolicyImprovementConfig,
        require_bound: bool,
    ) -> dict[Channel, float]:
        if cfg.bound_mode == "gaussian_reference":
            assert cfg.confidence_z is not None
            return {
                row.action: row.expected_cost + cfg.confidence_z * row.cost_uncertainty
                for row in rows
            }
        if require_bound:
            missing = [row.action.value for row in rows if row.cost_upper_bound is None]
            if missing:
                raise ValueError(
                    "hard expected-cost constraints require cost_upper_bound for every action; "
                    f"missing={sorted(missing)}"
                )
        return {
            row.action: (
                float(row.cost_upper_bound)
                if row.cost_upper_bound is not None
                else row.expected_cost
            )
            for row in rows
        }

    @staticmethod
    def _anchor_proposal(
        *,
        cfg: SafePolicyImprovementConfig,
        proposal: Mapping[Channel, float],
        behavior: Mapping[Channel, float],
        supported: set[Channel],
    ) -> tuple[dict[Channel, float], bool]:
        """Apply a SPIBB-style support constraint before interpolation."""

        actions = tuple(behavior)
        anchored: dict[Channel, float] = {}
        constrained = False
        fixed_mass = 0.0

        for action in actions:
            if action in supported:
                continue
            if cfg.unsupported_action_mode == "freeze":
                probability = behavior[action]
            else:
                probability = min(proposal[action], behavior[action])
            anchored[action] = probability
            fixed_mass += probability
            constrained = constrained or abs(probability - proposal[action]) > 1e-12

        movable_mass = max(0.0, 1.0 - fixed_mass)
        supported_proposal_mass = fsum(proposal[action] for action in supported)
        if supported_proposal_mass > 1e-15:
            supported_reference = {
                action: proposal[action] / supported_proposal_mass for action in supported
            }
        else:
            behavior_mass = fsum(behavior[action] for action in supported)
            if behavior_mass <= 1e-15:
                raise ValueError("supported action mass must be positive")
            supported_reference = {
                action: behavior[action] / behavior_mass for action in supported
            }
            constrained = True

        for action in supported:
            anchored[action] = movable_mass * supported_reference[action]

        total = fsum(anchored.values())
        if total <= 0.0:
            raise ValueError("anchored proposal has no probability mass")
        if abs(total - 1.0) > 1e-12:
            anchored = {action: probability / total for action, probability in anchored.items()}
        return anchored, constrained

    @staticmethod
    def _policy_value(
        probabilities: Mapping[Channel, float],
        action_values: Mapping[Channel, float],
    ) -> float:
        return fsum(probabilities[action] * action_values[action] for action in probabilities)

    @staticmethod
    def _total_variation(
        left: Mapping[Channel, float],
        right: Mapping[Channel, float],
    ) -> float:
        return 0.5 * fsum(abs(left[action] - right[action]) for action in left)

    def improve(
        self,
        estimates: Iterable[ActionValueEstimate],
        *,
        proposal_probabilities: Mapping[Channel, float] | None = None,
        max_expected_cost: float | None = None,
    ) -> PolicyImprovementResult:
        rows = list(estimates)
        if not rows:
            raise ValueError("at least one action estimate is required")
        if len({row.action for row in rows}) != len(rows):
            raise ValueError("action estimates must be unique by action")
        actions = tuple(row.action for row in rows)
        if Channel.NO_TREATMENT not in actions:
            raise ValueError("NO_TREATMENT estimate is required as a safe fallback")
        if max_expected_cost is not None and (
            not isfinite(max_expected_cost) or max_expected_cost < 0
        ):
            raise ValueError("max_expected_cost must be finite and non-negative")

        cfg = self._require_config()
        behavior = self._validate_distribution(
            {row.action: row.behavior_probability for row in rows},
            actions,
            name="behavior",
        )
        value_lcb = self._value_bounds(rows, cfg)
        cost_ucb = self._cost_bounds(
            rows,
            cfg=cfg,
            require_bound=max_expected_cost is not None,
        )
        baseline_value = self._policy_value(behavior, value_lcb)
        baseline_cost = self._policy_value(behavior, cost_ucb)

        if max_expected_cost is not None and baseline_cost > max_expected_cost:
            fallback = {action: 0.0 for action in actions}
            fallback[Channel.NO_TREATMENT] = 1.0
            return PolicyImprovementResult(
                probabilities=fallback,
                selected_action=Channel.NO_TREATMENT,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=value_lcb[Channel.NO_TREATMENT],
                expected_cost_ucb=cost_ucb[Channel.NO_TREATMENT],
                total_variation_distance=self._total_variation(behavior, fallback),
                changed=fallback != behavior,
                safe_fallback=True,
                reasons=("behavior_policy_cost_above_hard_limit",),
            )

        supported = {
            row.action
            for row in rows
            if row.action is Channel.NO_TREATMENT or row.support_eligible is True
        }
        unsupported_count = len(rows) - len(supported)
        unknown_support_count = sum(
            row.action is not Channel.NO_TREATMENT and row.support_eligible is None
            for row in rows
        )

        if proposal_probabilities is None:
            selected = max(
                (row for row in rows if row.action in supported),
                key=lambda row: (value_lcb[row.action], row.action.value),
            )
            proposal = {action: 0.0 for action in actions}
            proposal[selected.action] = 1.0
            used_reference_proposal = True
        else:
            proposal = self._validate_distribution(
                proposal_probabilities,
                actions,
                name="proposal",
            )
            used_reference_proposal = False

        anchored, support_constrained = self._anchor_proposal(
            cfg=cfg,
            proposal=proposal,
            behavior=behavior,
            supported=supported,
        )
        proposal_value = self._policy_value(anchored, value_lcb)
        proposal_cost = self._policy_value(anchored, cost_ucb)

        reasons: list[str] = []
        if used_reference_proposal:
            reasons.append("reference_pessimistic_proposal_used")
        if unsupported_count:
            reasons.append("unsupported_actions_anchored")
        if unknown_support_count:
            reasons.append("missing_action_support_treated_as_unsupported")
        if support_constrained:
            reasons.append("proposal_support_constraint_active")
        if cfg.bound_mode == "gaussian_reference":
            reasons.append("gaussian_reference_bounds_used")

        direction_tv = self._total_variation(behavior, anchored)
        if direction_tv <= 1e-15:
            selected_action = max(actions, key=lambda action: (anchored[action], action.value))
            return PolicyImprovementResult(
                probabilities=behavior,
                selected_action=selected_action,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=baseline_value,
                expected_cost_ucb=baseline_cost,
                total_variation_distance=0.0,
                changed=False,
                reasons=tuple(reasons + ["proposal_matches_behavior_after_anchoring"]),
            )

        proposal_gain = proposal_value - baseline_value
        if proposal_gain <= 0.0:
            selected_action = max(
                actions,
                key=lambda action: (anchored[action] - behavior[action], action.value),
            )
            return PolicyImprovementResult(
                probabilities=behavior,
                selected_action=selected_action,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=baseline_value,
                expected_cost_ucb=baseline_cost,
                total_variation_distance=0.0,
                changed=False,
                reasons=tuple(reasons + ["no_pessimistic_improvement"]),
            )

        mixture = min(1.0, cfg.max_total_variation / direction_tv)
        if mixture < 1.0:
            reasons.append("total_variation_cap_active")

        if max_expected_cost is not None and proposal_cost > baseline_cost:
            allowed_mix = (max_expected_cost - baseline_cost) / (proposal_cost - baseline_cost)
            allowed_mix = max(0.0, min(1.0, allowed_mix))
            if allowed_mix < mixture:
                mixture = allowed_mix
                reasons.append("expected_cost_cap_active")

        if mixture <= 1e-12:
            selected_action = max(
                actions,
                key=lambda action: (anchored[action] - behavior[action], action.value),
            )
            return PolicyImprovementResult(
                probabilities=behavior,
                selected_action=selected_action,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=baseline_value,
                expected_cost_ucb=baseline_cost,
                total_variation_distance=0.0,
                changed=False,
                reasons=tuple(reasons + ["safe_update_mass_is_zero"]),
            )

        candidate = {
            action: behavior[action] + mixture * (anchored[action] - behavior[action])
            for action in actions
        }
        candidate_value = self._policy_value(candidate, value_lcb)
        candidate_cost = self._policy_value(candidate, cost_ucb)
        total_variation = self._total_variation(behavior, candidate)

        if candidate_value - baseline_value + 1e-12 < cfg.min_pessimistic_improvement:
            selected_action = max(
                actions,
                key=lambda action: (candidate[action] - behavior[action], action.value),
            )
            return PolicyImprovementResult(
                probabilities=behavior,
                selected_action=selected_action,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=baseline_value,
                expected_cost_ucb=baseline_cost,
                total_variation_distance=0.0,
                changed=False,
                reasons=tuple(reasons + ["minimum_pessimistic_gain_not_reached"]),
            )

        selected_action = max(
            actions,
            key=lambda action: (
                candidate[action] - behavior[action],
                candidate[action],
                action.value,
            ),
        )
        reasons.append("safe_behavior_anchored_update")
        return PolicyImprovementResult(
            probabilities=candidate,
            selected_action=selected_action,
            pessimistic_baseline_value=baseline_value,
            pessimistic_candidate_value=candidate_value,
            expected_cost_ucb=candidate_cost,
            total_variation_distance=total_variation,
            changed=True,
            reasons=tuple(reasons),
        )
