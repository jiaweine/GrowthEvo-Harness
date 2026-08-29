from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite
from typing import Iterable, Literal, Mapping

from growthevo.models import Channel


@dataclass(frozen=True, slots=True)
class ActionValueEstimate:
    """One action's value/cost evidence for conservative policy improvement.

    ``value_uncertainty`` and ``cost_uncertainty`` are generic model diagnostics.
    They become Gaussian-style bounds only when the policy-improvement protocol
    explicitly selects ``gaussian_reference`` mode. Production/research promotion
    can instead provide calibrated or inferential ``value_lower_bound`` and
    ``cost_upper_bound`` values directly.

    ``support_eligible`` is an explicit upstream evidence decision. When absent,
    backwards-compatible behavior-probability support can be used by config; a
    fail-closed protocol can require explicit support for every treatment action.
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
                raise ValueError("cost_upper_bound cannot be below expected_cost")

        if self.action is Channel.NO_TREATMENT:
            if self.expected_cost != 0.0:
                raise ValueError("NO_TREATMENT expected_cost must be zero")
            if self.cost_upper_bound not in {None, 0.0}:
                raise ValueError("NO_TREATMENT cost_upper_bound must be zero when provided")


@dataclass(frozen=True, slots=True)
class SafePolicyImprovementConfig:
    """Trust-region, bound, and support semantics for safe policy improvement.

    ``gaussian_reference`` preserves the historical reference implementation and
    is useful for synthetic regression tests. ``provided`` is the stronger safety
    mode: lower/upper bounds must come from an upstream calibrated/inferential
    protocol and are not manufactured from a generic uncertainty score.

    ``support_mode='explicit'`` fails closed when a treatment action lacks an
    explicit support decision. ``behavior_floor`` is retained for compatibility
    and as a simple reference protocol.
    """

    confidence_z: float = 1.96
    support_floor: float = 0.02
    max_total_variation: float = 0.20
    min_pessimistic_improvement: float = 0.0
    bound_mode: Literal["gaussian_reference", "provided"] = "gaussian_reference"
    support_mode: Literal["behavior_floor", "explicit"] = "behavior_floor"
    unsupported_action_mode: Literal["no_increase", "freeze"] = "no_increase"

    def __post_init__(self) -> None:
        if not isfinite(self.confidence_z) or self.confidence_z < 0:
            raise ValueError("confidence_z must be non-negative and finite")
        if not isfinite(self.support_floor) or not 0 < self.support_floor <= 1:
            raise ValueError("support_floor must be in (0, 1]")
        if not isfinite(self.max_total_variation) or not 0 <= self.max_total_variation <= 1:
            raise ValueError("max_total_variation must be in [0, 1]")
        if (
            not isfinite(self.min_pessimistic_improvement)
            or self.min_pessimistic_improvement < 0
        ):
            raise ValueError("min_pessimistic_improvement must be non-negative")
        if self.bound_mode not in {"gaussian_reference", "provided"}:
            raise ValueError("unsupported bound_mode")
        if self.support_mode not in {"behavior_floor", "explicit"}:
            raise ValueError("unsupported support_mode")
        if self.unsupported_action_mode not in {"no_increase", "freeze"}:
            raise ValueError("unsupported_action_mode must be no_increase or freeze")


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


@dataclass(frozen=True, slots=True)
class _CandidateDirection:
    name: str
    distribution: Mapping[Channel, float]
    selected_action: Channel


class SupportAnchoredPolicyImprover:
    """Pessimistic feasible policy search anchored to logged support.

    The algorithm combines two useful conservative-policy ideas:

    1. evaluate *final feasible* per-action candidates instead of selecting a raw
       argmax and clipping it afterwards; and
    2. optionally evaluate a learned proposal distribution after SPIBB-style
       support anchoring.

    Every candidate is interpolated from the behavior policy only as far as the
    total-variation and expected-cost constraints allow. The winner is chosen by
    final pessimistic policy value, so a flashy action with almost zero feasible
    update mass cannot hide a slightly lower-valued but materially actionable
    alternative.
    """

    def __init__(self, config: SafePolicyImprovementConfig | None = None) -> None:
        self.config = config or SafePolicyImprovementConfig()

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
    ) -> dict[Channel, float]:
        cfg = self.config
        if cfg.bound_mode == "gaussian_reference":
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
        require_bounds: bool,
    ) -> dict[Channel, float]:
        cfg = self.config
        if cfg.bound_mode == "gaussian_reference":
            return {
                row.action: row.expected_cost + cfg.confidence_z * row.cost_uncertainty
                for row in rows
            }
        if require_bounds:
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

    def _supported_actions(
        self,
        rows: list[ActionValueEstimate],
    ) -> tuple[set[Channel], bool]:
        cfg = self.config
        supported = {Channel.NO_TREATMENT}
        missing_explicit = False
        for row in rows:
            if row.action is Channel.NO_TREATMENT:
                continue
            if row.support_eligible is True:
                supported.add(row.action)
            elif row.support_eligible is False:
                continue
            elif cfg.support_mode == "behavior_floor":
                if row.behavior_probability >= cfg.support_floor:
                    supported.add(row.action)
            else:
                missing_explicit = True
        return supported, missing_explicit

    @staticmethod
    def _policy_value(
        probabilities: Mapping[Channel, float],
        values: Mapping[Channel, float],
    ) -> float:
        return fsum(probabilities[action] * values[action] for action in probabilities)

    @staticmethod
    def _total_variation(
        left: Mapping[Channel, float],
        right: Mapping[Channel, float],
    ) -> float:
        return 0.5 * fsum(abs(left[action] - right[action]) for action in left)

    def _anchor_proposal(
        self,
        proposal: Mapping[Channel, float],
        behavior: Mapping[Channel, float],
        supported: set[Channel],
    ) -> tuple[dict[Channel, float], bool]:
        cfg = self.config
        anchored: dict[Channel, float] = {}
        fixed_mass = 0.0
        changed = False
        for action in behavior:
            if action in supported:
                continue
            if cfg.unsupported_action_mode == "freeze":
                probability = behavior[action]
            else:
                probability = min(proposal[action], behavior[action])
            anchored[action] = probability
            fixed_mass += probability
            changed = changed or abs(probability - proposal[action]) > 1e-12

        movable_mass = max(0.0, 1.0 - fixed_mass)
        proposed_supported_mass = fsum(proposal[action] for action in supported)
        if proposed_supported_mass > 1e-15:
            reference = {
                action: proposal[action] / proposed_supported_mass
                for action in supported
            }
        else:
            behavior_supported_mass = fsum(behavior[action] for action in supported)
            if behavior_supported_mass <= 1e-15:
                raise ValueError("supported action mass must be positive")
            reference = {
                action: behavior[action] / behavior_supported_mass
                for action in supported
            }
            changed = True
        for action in supported:
            anchored[action] = movable_mass * reference[action]

        total = fsum(anchored.values())
        if total <= 0:
            raise ValueError("anchored proposal has no probability mass")
        if abs(total - 1.0) > 1e-12:
            anchored = {action: probability / total for action, probability in anchored.items()}
        return anchored, changed

    def _max_feasible_mix(
        self,
        behavior: Mapping[Channel, float],
        target: Mapping[Channel, float],
        cost_ucb: Mapping[Channel, float],
        *,
        baseline_cost: float,
        max_expected_cost: float | None,
    ) -> tuple[float, bool, bool]:
        cfg = self.config
        direction_tv = self._total_variation(behavior, target)
        if direction_tv <= 1e-15:
            return 0.0, False, False

        mixture = min(1.0, cfg.max_total_variation / direction_tv)
        tv_cap_active = mixture < 1.0
        cost_cap_active = False

        if max_expected_cost is not None:
            target_cost = self._policy_value(target, cost_ucb)
            if target_cost > baseline_cost:
                allowed_mix = (
                    (max_expected_cost - baseline_cost)
                    / (target_cost - baseline_cost)
                )
                allowed_mix = max(0.0, min(1.0, allowed_mix))
                if allowed_mix < mixture:
                    mixture = allowed_mix
                    cost_cap_active = True
        return mixture, tv_cap_active, cost_cap_active

    def improve(
        self,
        estimates: Iterable[ActionValueEstimate],
        *,
        max_expected_cost: float | None = None,
        proposal_probabilities: Mapping[Channel, float] | None = None,
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

        behavior = self._validate_distribution(
            {row.action: row.behavior_probability for row in rows},
            actions,
            name="behavior",
        )
        value_lcb = self._value_bounds(rows)
        cost_ucb = self._cost_bounds(
            rows,
            require_bounds=max_expected_cost is not None,
        )
        baseline_value = self._policy_value(behavior, value_lcb)
        baseline_cost = self._policy_value(behavior, cost_ucb)

        if max_expected_cost is not None and baseline_cost > max_expected_cost:
            if cost_ucb[Channel.NO_TREATMENT] > max_expected_cost:
                raise ValueError("NO_TREATMENT does not satisfy the hard cost limit")
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

        supported, missing_explicit = self._supported_actions(rows)
        reasons: list[str] = []
        if len(supported) != len(rows):
            reasons.append("unsupported_actions_anchored")
        if missing_explicit:
            reasons.append("missing_action_support_treated_as_unsupported")
        if self.config.bound_mode == "gaussian_reference":
            reasons.append("gaussian_reference_bounds_used")

        directions: list[_CandidateDirection] = []
        for row in rows:
            if row.action not in supported:
                continue
            target = {action: 0.0 for action in actions}
            target[row.action] = 1.0
            directions.append(
                _CandidateDirection(
                    name=f"action:{row.action.value}",
                    distribution=target,
                    selected_action=row.action,
                )
            )

        if proposal_probabilities is not None:
            proposal = self._validate_distribution(
                proposal_probabilities,
                actions,
                name="proposal",
            )
            anchored, constrained = self._anchor_proposal(
                proposal,
                behavior,
                supported,
            )
            selected_action = max(
                actions,
                key=lambda action: (
                    anchored[action] - behavior[action],
                    anchored[action],
                    action.value,
                ),
            )
            directions.append(
                _CandidateDirection(
                    name="anchored_proposal",
                    distribution=anchored,
                    selected_action=selected_action,
                )
            )
            if constrained:
                reasons.append("proposal_support_constraint_active")

        feasible: list[
            tuple[
                float,
                float,
                float,
                float,
                _CandidateDirection,
                dict[Channel, float],
                bool,
                bool,
            ]
        ] = []
        nonzero_update_exists = False
        cost_blocked = False

        for direction in directions:
            mixture, tv_cap_active, cost_cap_active = self._max_feasible_mix(
                behavior,
                direction.distribution,
                cost_ucb,
                baseline_cost=baseline_cost,
                max_expected_cost=max_expected_cost,
            )
            if mixture <= 1e-12:
                cost_blocked = cost_blocked or cost_cap_active
                continue
            nonzero_update_exists = True

            candidate = {
                action: behavior[action]
                + mixture * (direction.distribution[action] - behavior[action])
                for action in actions
            }
            candidate_value = self._policy_value(candidate, value_lcb)
            candidate_cost = self._policy_value(candidate, cost_ucb)
            gain = candidate_value - baseline_value
            if gain <= self.config.min_pessimistic_improvement + 1e-12:
                continue
            feasible.append(
                (
                    candidate_value,
                    -candidate_cost,
                    gain,
                    mixture,
                    direction,
                    candidate,
                    tv_cap_active,
                    cost_cap_active,
                )
            )

        if not feasible:
            supported_rows = [row for row in rows if row.action in supported]
            selected = max(
                supported_rows,
                key=lambda row: (value_lcb[row.action], row.action.value),
            )
            final_reasons = list(reasons)
            if cost_blocked:
                final_reasons.append("expected_cost_cap_active")
            if nonzero_update_exists:
                final_reasons.append("min_pessimistic_improvement_not_met")
            else:
                final_reasons.append("safe_update_mass_is_zero")
            return PolicyImprovementResult(
                probabilities=behavior,
                selected_action=selected.action,
                pessimistic_baseline_value=baseline_value,
                pessimistic_candidate_value=baseline_value,
                expected_cost_ucb=baseline_cost,
                total_variation_distance=0.0,
                changed=False,
                reasons=tuple(final_reasons),
            )

        (
            candidate_value,
            neg_candidate_cost,
            _gain,
            mixture,
            direction,
            candidate,
            tv_cap_active,
            cost_cap_active,
        ) = max(
            feasible,
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3],
                item[4].name,
            ),
        )
        candidate_cost = -neg_candidate_cost
        final_reasons = reasons + ["pessimistic_feasible_policy_selected"]
        if direction.name == "anchored_proposal":
            final_reasons.append("learned_proposal_selected")
        else:
            final_reasons.append("per_action_candidate_selected")
        if tv_cap_active:
            final_reasons.append("total_variation_cap_active")
        if cost_cap_active:
            final_reasons.append("expected_cost_cap_active")

        return PolicyImprovementResult(
            probabilities=candidate,
            selected_action=direction.selected_action,
            pessimistic_baseline_value=baseline_value,
            pessimistic_candidate_value=candidate_value,
            expected_cost_ucb=candidate_cost,
            total_variation_distance=self._total_variation(behavior, candidate),
            changed=any(
                abs(candidate[action] - behavior[action]) > 1e-12
                for action in actions
            ),
            reasons=tuple(final_reasons),
        )