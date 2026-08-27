from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class GrowthOption(str, Enum):
    ACQUIRE = "acquire"
    ACTIVATE = "activate"
    RETAIN = "retain"
    REACTIVATE = "reactivate"
    UPSELL = "upsell"
    EXPLORE = "explore"
    HOLDOUT = "holdout"
    STOP = "stop"


class Channel(str, Enum):
    NO_TREATMENT = "no_treatment"
    PUSH = "push"
    EMAIL = "email"
    IN_APP = "in_app"
    ADS = "ads"


class EventType(str, Enum):
    GOAL_COMPILED = "goal_compiled"
    BELIEF_UPDATED = "belief_updated"
    HYPOTHESIS_PLANNED = "hypothesis_planned"
    ACTION_PROPOSED = "action_proposed"
    ACTION_ALLOWED = "action_allowed"
    ACTION_BLOCKED = "action_blocked"
    FEEDBACK_OBSERVED = "feedback_observed"
    REWARD_ASSIGNED = "reward_assigned"
    PROCESS_REWARD_ASSIGNED = "process_reward_assigned"
    ROLLOUT_EVALUATED = "rollout_evaluated"
    VERIFICATION_COMPLETED = "verification_completed"
    FAILURE_CLASSIFIED = "failure_classified"
    PATCH_PROPOSED = "patch_proposed"


class VerificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class FailureKind(str, Enum):
    ATTRIBUTION = "attribution"
    BUDGET = "budget"
    FATIGUE = "fatigue"
    ROI = "roi"
    UNCERTAINTY = "uncertainty"
    CONSENT = "consent"
    DISTRIBUTION_SHIFT = "distribution_shift"
    TOOL = "tool"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GrowthConstraints:
    max_budget: float
    min_roi: float = 1.0
    max_fatigue: float = 0.8
    max_churn_risk: float = 0.5
    max_touches_24h: int = 2
    max_touches_7d: int = 6
    max_offer_value: float = 20.0

    def __post_init__(self) -> None:
        if self.max_budget < 0:
            raise ValueError("max_budget must be non-negative")
        if self.min_roi < 0:
            raise ValueError("min_roi must be non-negative")
        if not 0 <= self.max_fatigue <= 1:
            raise ValueError("max_fatigue must be in [0, 1]")
        if not 0 <= self.max_churn_risk <= 1:
            raise ValueError("max_churn_risk must be in [0, 1]")
        if self.max_touches_24h < 0 or self.max_touches_7d < 0:
            raise ValueError("touch limits must be non-negative")
        if self.max_offer_value < 0:
            raise ValueError("max_offer_value must be non-negative")


@dataclass(frozen=True, slots=True)
class GrowthGoal:
    metric: str
    horizon_days: int
    target_delta: float
    constraints: GrowthConstraints

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric cannot be empty")
        if self.horizon_days <= 0:
            raise ValueError("horizon_days must be positive")


def _validate_channel_diagnostics(
    *,
    channel_uplift: Mapping[Channel, float],
    channel_uncertainty: Mapping[Channel, float],
    channel_support: Mapping[Channel, float],
    channel_effect_lower_bound: Mapping[Channel, float],
) -> None:
    for channel, uplift in channel_uplift.items():
        if channel is Channel.NO_TREATMENT:
            raise ValueError("NO_TREATMENT cannot have treatment uplift")
        if not -1 <= uplift <= 1:
            raise ValueError("channel uplift must be in [-1, 1]")
    for name, values in (
        ("channel_uncertainty", channel_uncertainty),
        ("channel_support", channel_support),
    ):
        for channel, value in values.items():
            if channel is Channel.NO_TREATMENT:
                raise ValueError(f"NO_TREATMENT cannot appear in {name}")
            if not 0 <= value <= 1:
                raise ValueError(f"{name} values must be in [0, 1]")
    for channel, lower_bound in channel_effect_lower_bound.items():
        if channel is Channel.NO_TREATMENT:
            raise ValueError("NO_TREATMENT cannot have an effect lower bound")
        if channel not in channel_uplift:
            raise ValueError("effect lower bound requires a corresponding channel uplift")
        if not -1 <= lower_bound <= 1:
            raise ValueError("channel effect lower bounds must be in [-1, 1]")
        if lower_bound > float(channel_uplift[channel]) + 1e-12:
            raise ValueError("effect lower bound cannot exceed the point uplift estimate")


@dataclass(frozen=True, slots=True)
class UserObservation:
    user_id: str
    natural_conversion: float
    channel_uplift: Mapping[Channel, float]
    uplift_uncertainty: float
    ltv: float
    channel_uncertainty: Mapping[Channel, float] = field(default_factory=dict)
    channel_support: Mapping[Channel, float] = field(default_factory=dict)
    channel_effect_lower_bound: Mapping[Channel, float] = field(default_factory=dict)
    fatigue: float = 0.0
    churn_risk: float = 0.0
    touches_24h: int = 0
    touches_7d: int = 0
    spend_to_date: float = 0.0
    days_since_last_active: int = 0
    lifecycle_stage: str = "active"
    consented_channels: frozenset[Channel] = field(
        default_factory=lambda: frozenset({Channel.PUSH, Channel.EMAIL, Channel.IN_APP, Channel.ADS})
    )

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id cannot be empty")
        for name, value in (
            ("natural_conversion", self.natural_conversion),
            ("uplift_uncertainty", self.uplift_uncertainty),
            ("fatigue", self.fatigue),
            ("churn_risk", self.churn_risk),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.ltv < 0 or self.spend_to_date < 0:
            raise ValueError("ltv and spend_to_date must be non-negative")
        if self.touches_24h < 0 or self.touches_7d < 0:
            raise ValueError("touch counts must be non-negative")
        if self.days_since_last_active < 0:
            raise ValueError("days_since_last_active must be non-negative")
        _validate_channel_diagnostics(
            channel_uplift=self.channel_uplift,
            channel_uncertainty=self.channel_uncertainty,
            channel_support=self.channel_support,
            channel_effect_lower_bound=self.channel_effect_lower_bound,
        )


@dataclass(frozen=True, slots=True)
class CausalBelief:
    user_id: str
    natural_conversion: float
    channel_uplift: Mapping[Channel, float]
    uplift_uncertainty: float
    ltv: float
    fatigue: float
    churn_risk: float
    touches_24h: int
    touches_7d: int
    spend_to_date: float
    days_since_last_active: int
    lifecycle_stage: str
    consented_channels: frozenset[Channel]
    channel_uncertainty: Mapping[Channel, float] = field(default_factory=dict)
    channel_support: Mapping[Channel, float] = field(default_factory=dict)
    channel_effect_lower_bound: Mapping[Channel, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id cannot be empty")
        if not 0 <= self.uplift_uncertainty <= 1:
            raise ValueError("uplift_uncertainty must be in [0, 1]")
        _validate_channel_diagnostics(
            channel_uplift=self.channel_uplift,
            channel_uncertainty=self.channel_uncertainty,
            channel_support=self.channel_support,
            channel_effect_lower_bound=self.channel_effect_lower_bound,
        )

    def uplift_for(self, channel: Channel) -> float:
        if channel is Channel.NO_TREATMENT:
            return 0.0
        return float(self.channel_uplift.get(channel, 0.0))

    def uncertainty_for(self, channel: Channel) -> float:
        if channel is Channel.NO_TREATMENT:
            return 0.0
        return float(self.channel_uncertainty.get(channel, self.uplift_uncertainty))

    def support_for(self, channel: Channel) -> float:
        """Return declared logging support; unknown treatment support fails closed."""

        if channel is Channel.NO_TREATMENT:
            return 1.0
        return float(self.channel_support.get(channel, 0.0))

    def effect_lower_bound_for(self, channel: Channel) -> float | None:
        if channel is Channel.NO_TREATMENT:
            return 0.0
        value = self.channel_effect_lower_bound.get(channel)
        return None if value is None else float(value)


@dataclass(frozen=True, slots=True)
class GrowthAction:
    option: GrowthOption
    channel: Channel
    offer_value: float = 0.0
    budget: float = 0.0
    frequency_cost: float = 0.0
    expected_uplift: float = 0.0
    uncertainty: float = 0.0
    creative_id: str | None = None
    send_hour: int | None = None

    def __post_init__(self) -> None:
        if self.offer_value < 0 or self.budget < 0 or self.frequency_cost < 0:
            raise ValueError("offer_value, budget and frequency_cost must be non-negative")
        if not 0 <= self.uncertainty <= 1:
            raise ValueError("uncertainty must be in [0, 1]")
        if self.send_hour is not None and not 0 <= self.send_hour <= 23:
            raise ValueError("send_hour must be in [0, 23]")
        if self.channel is Channel.NO_TREATMENT:
            if self.offer_value != 0 or self.budget != 0 or self.frequency_cost != 0:
                raise ValueError("NO_TREATMENT cannot spend budget, offer value or frequency")
            if self.expected_uplift != 0:
                raise ValueError("NO_TREATMENT expected_uplift must be zero")

    @classmethod
    def no_treatment(cls, option: GrowthOption = GrowthOption.HOLDOUT) -> "GrowthAction":
        return cls(option=option, channel=Channel.NO_TREATMENT)


@dataclass(frozen=True, slots=True)
class Feedback:
    realized_conversion: bool
    treatment_conversion_prob: float
    baseline_conversion_prob: float
    incremental_ltv: float
    retention_delta: float
    cost: float
    fatigue_delta: float
    churn_risk_delta: float
    delay_days: int = 0

    @property
    def incremental_conversion(self) -> float:
        return self.treatment_conversion_prob - self.baseline_conversion_prob


@dataclass(frozen=True, slots=True)
class RewardBreakdown:
    incremental_conversion: float
    incremental_ltv: float
    retention: float
    cost_penalty: float
    fatigue_penalty: float
    risk_penalty: float
    uncertainty_penalty: float
    total: float


@dataclass(frozen=True, slots=True)
class PolicyEvidence:
    candidate_value: float
    baseline_value: float
    standard_error: float
    sample_size: int
    effective_sample_size: float
    roi: float
    spend: float
    fatigue: float
    churn_risk: float
    support_coverage: float = 1.0
    max_importance_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.sample_size < 0:
            raise ValueError("sample_size must be non-negative")
        if self.effective_sample_size < 0:
            raise ValueError("effective_sample_size must be non-negative")
        if not 0 <= self.support_coverage <= 1:
            raise ValueError("support_coverage must be in [0, 1]")
        if self.max_importance_weight < 0:
            raise ValueError("max_importance_weight must be non-negative")

    @property
    def effective_sample_ratio(self) -> float:
        if self.sample_size == 0:
            return 0.0
        return min(1.0, self.effective_sample_size / self.sample_size)


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    value_delta: float
    lower_confidence_bound: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HarnessPatch:
    coordinate: str
    value: Any
    rationale: str
    source_failure: FailureKind


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    belief: CausalBelief
    action: GrowthAction
    feedback: Feedback
    reward: RewardBreakdown
    event_count: int


def to_primitive(value: Any) -> Any:
    """Convert typed runtime values into deterministic JSON-compatible primitives."""

    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return to_primitive(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(to_primitive(key)): to_primitive(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset, tuple, list)):
        items = [to_primitive(item) for item in value]
        if isinstance(value, (set, frozenset)):
            return sorted(items, key=str)
        return items
    return value
