from __future__ import annotations

from dataclasses import dataclass, replace
from math import ceil, fsum, isfinite, log, sqrt
from typing import Callable, Iterable, Sequence

from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthConstraints
from growthevo.rl.causal_reward import CausalRewardModel
from growthevo.simulator.user_world_model import UserWorldModel, WorldModelConfig


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True, slots=True)
class WorldTransitionConfig:
    fatigue_decay_per_step: float = 0.06
    churn_recovery_per_step: float = 0.01
    retention_to_intent: float = 0.15
    fatigue_uplift_decay: float = 0.20

    def __post_init__(self) -> None:
        for name, value in (
            ("fatigue_decay_per_step", self.fatigue_decay_per_step),
            ("churn_recovery_per_step", self.churn_recovery_per_step),
            ("retention_to_intent", self.retention_to_intent),
            ("fatigue_uplift_decay", self.fatigue_uplift_decay),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0 <= self.fatigue_decay_per_step <= 1:
            raise ValueError("fatigue_decay_per_step must be in [0, 1]")
        if self.churn_recovery_per_step < 0:
            raise ValueError("churn_recovery_per_step must be non-negative")
        if self.retention_to_intent < 0:
            raise ValueError("retention_to_intent must be non-negative")
        if self.fatigue_uplift_decay < 0:
            raise ValueError("fatigue_uplift_decay must be non-negative")


@dataclass(frozen=True, slots=True)
class StressScenario:
    """Deployment-shift knobs used for conservative world-model stress tests."""

    uplift_multiplier: float = 1.0
    cost_multiplier: float = 1.0
    fatigue_multiplier: float = 1.0

    def __post_init__(self) -> None:
        for name, value in (
            ("uplift_multiplier", self.uplift_multiplier),
            ("cost_multiplier", self.cost_multiplier),
            ("fatigue_multiplier", self.fatigue_multiplier),
        ):
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class RolloutTrace:
    discounted_return: float
    total_cost: float
    max_fatigue: float
    max_churn_risk: float
    violated: bool
    final_belief: CausalBelief


@dataclass(frozen=True, slots=True)
class CandidateRolloutScore:
    """World-model rollout diagnostics for one candidate plan.

    ``violation_rate`` is the empirical simulator violation frequency.
    ``monte_carlo_violation_ucb`` adds a distribution-free Hoeffding bound for
    finite rollout sampling error only. It does *not* cover world-model bias or
    deployment shift, so this object must not be treated as real-world policy
    safety evidence without separate model validation/stress protocols.
    """

    candidate_id: str
    mean_return: float
    cvar_return: float
    violation_rate: float
    monte_carlo_violation_ucb: float
    monte_carlo_delta: float
    rollout_count: int
    mean_cost: float
    robust_score: float
    feasible: bool


@dataclass(frozen=True, slots=True)
class RiskSensitiveMPCConfig:
    """Explicit Monte Carlo risk protocol for model-based plan ranking."""

    rollouts: int
    cvar_alpha: float
    violation_penalty: float
    max_violation_rate: float
    monte_carlo_delta: float
    gamma: float
    base_seed: int

    def __post_init__(self) -> None:
        if self.rollouts <= 0:
            raise ValueError("rollouts must be positive")
        if not isfinite(self.cvar_alpha) or not 0 < self.cvar_alpha <= 1:
            raise ValueError("cvar_alpha must be a finite value in (0, 1]")
        if not isfinite(self.violation_penalty) or self.violation_penalty < 0:
            raise ValueError("violation_penalty must be finite and non-negative")
        if not isfinite(self.max_violation_rate) or not 0 <= self.max_violation_rate <= 1:
            raise ValueError("max_violation_rate must be a finite value in [0, 1]")
        if not isfinite(self.monte_carlo_delta) or not 0 < self.monte_carlo_delta < 1:
            raise ValueError("monte_carlo_delta must be a finite value in (0, 1)")
        if not isfinite(self.gamma) or not 0 < self.gamma <= 1:
            raise ValueError("gamma must be a finite value in (0, 1]")


TouchStateUpdater = Callable[[CausalBelief, bool, int], tuple[int, int]]


def conservative_touch_accumulator(
    belief: CausalBelief,
    treated: bool,
    elapsed_days: int,
) -> tuple[int, int]:
    """Conservatively retain prior touch counts throughout a simulated plan.

    The compact belief stores counts but not historical touch timestamps, so the
    reference world cannot know exactly which touches expire from rolling 24h/7d
    windows. It therefore never invents expiry. Production worlds can inject an
    exact calendar-backed updater using ``elapsed_days``.
    """

    del elapsed_days
    increment = int(treated)
    return belief.touches_24h + increment, belief.touches_7d + increment


class LongHorizonGrowthWorld:
    """State-transition wrapper around a one-step stochastic user model."""

    def __init__(
        self,
        *,
        seed: int,
        world_config: WorldModelConfig | None = None,
        transition_config: WorldTransitionConfig | None = None,
        reward_model: CausalRewardModel | None = None,
        touch_state_updater: TouchStateUpdater = conservative_touch_accumulator,
    ) -> None:
        self.world = UserWorldModel(seed=seed, config=world_config)
        self.transition_config = transition_config or WorldTransitionConfig()
        self.reward_model = reward_model or CausalRewardModel()
        self.touch_state_updater = touch_state_updater

    def transition(
        self,
        belief: CausalBelief,
        action: GrowthAction,
        *,
        stress: StressScenario | None = None,
    ) -> tuple[CausalBelief, float, float]:
        scenario = stress or StressScenario()
        stressed_action = replace(
            action,
            expected_uplift=action.expected_uplift * scenario.uplift_multiplier,
            budget=action.budget * scenario.cost_multiplier,
        )
        feedback = self.world.step(belief, stressed_action)
        reward = self.reward_model.compute(belief, stressed_action, feedback).total

        cfg = self.transition_config
        treated = action.channel is not Channel.NO_TREATMENT
        fatigue = _clip(
            (belief.fatigue + feedback.fatigue_delta * scenario.fatigue_multiplier)
            * (1.0 - cfg.fatigue_decay_per_step)
        )
        churn = _clip(
            belief.churn_risk + feedback.churn_risk_delta - cfg.churn_recovery_per_step
        )
        natural_conversion = _clip(
            belief.natural_conversion + cfg.retention_to_intent * feedback.retention_delta
        )
        uplift_decay = max(0.0, 1.0 - cfg.fatigue_uplift_decay * fatigue)
        channel_uplift = {
            channel: uplift * uplift_decay for channel, uplift in belief.channel_uplift.items()
        }
        touches_24h, touches_7d = self.touch_state_updater(
            belief,
            treated,
            feedback.delay_days,
        )
        if touches_24h < 0 or touches_7d < 0:
            raise ValueError("touch_state_updater returned negative touch counts")

        next_belief = replace(
            belief,
            natural_conversion=natural_conversion,
            channel_uplift=channel_uplift,
            fatigue=fatigue,
            churn_risk=churn,
            touches_24h=touches_24h,
            touches_7d=touches_7d,
            spend_to_date=belief.spend_to_date + feedback.cost,
            days_since_last_active=(
                0
                if feedback.realized_conversion
                else belief.days_since_last_active + feedback.delay_days
            ),
        )
        return next_belief, reward, feedback.cost

    def rollout(
        self,
        initial_belief: CausalBelief,
        actions: Sequence[GrowthAction],
        constraints: GrowthConstraints,
        *,
        gamma: float,
        stress: StressScenario | None = None,
    ) -> RolloutTrace:
        if not actions:
            raise ValueError("rollout requires at least one action")
        if not isfinite(gamma) or not 0 < gamma <= 1:
            raise ValueError("gamma must be a finite value in (0, 1]")

        belief = initial_belief
        discounted_return = 0.0
        total_cost = 0.0
        max_fatigue = belief.fatigue
        max_churn = belief.churn_risk
        violated = False

        for index, action in enumerate(actions):
            belief, reward, cost = self.transition(belief, action, stress=stress)
            discounted_return += (gamma**index) * reward
            total_cost += cost
            max_fatigue = max(max_fatigue, belief.fatigue)
            max_churn = max(max_churn, belief.churn_risk)
            if (
                belief.spend_to_date > constraints.max_budget
                or belief.fatigue > constraints.max_fatigue
                or belief.churn_risk > constraints.max_churn_risk
                or belief.touches_24h > constraints.max_touches_24h
                or belief.touches_7d > constraints.max_touches_7d
            ):
                violated = True

        return RolloutTrace(
            discounted_return=discounted_return,
            total_cost=total_cost,
            max_fatigue=max_fatigue,
            max_churn_risk=max_churn,
            violated=violated,
            final_belief=belief,
        )


WorldFactory = Callable[[int], LongHorizonGrowthWorld]


def _hoeffding_upper_rate(rate: float, sample_count: int, delta: float) -> float:
    """One-sided Monte Carlo sampling bound for a Bernoulli violation rate."""

    radius = sqrt(log(1.0 / delta) / (2.0 * sample_count))
    return min(1.0, rate + radius)


class RiskSensitiveMPC:
    """Rank open-loop plans under an explicit model and risk protocol.

    Candidate plans use common random numbers. Constraint feasibility is ranked
    before reward so a change in reward units cannot make an unsafe plan win by
    overwhelming an arbitrary scalar penalty.

    The caller must provide both ``RiskSensitiveMPCConfig`` and ``world_factory``.
    GrowthEvo does not silently select a simulator, CVaR tail, rollout count,
    discount factor, violation tolerance, or confidence budget.
    """

    def __init__(
        self,
        *,
        config: RiskSensitiveMPCConfig,
        world_factory: WorldFactory,
    ) -> None:
        if not callable(world_factory):
            raise ValueError("world_factory must be callable")
        self.config = config
        self.world_factory = world_factory

    def evaluate(
        self,
        initial_belief: CausalBelief,
        candidates: Iterable[tuple[str, Sequence[GrowthAction]]],
        constraints: GrowthConstraints,
        *,
        stress: StressScenario | None = None,
        rollout_seeds: Sequence[int] | None = None,
    ) -> tuple[CandidateRolloutScore, ...]:
        candidate_rows = [(candidate_id, tuple(actions)) for candidate_id, actions in candidates]
        if not candidate_rows:
            raise ValueError("at least one candidate plan is required")
        identifiers = [candidate_id for candidate_id, _ in candidate_rows]
        if any(not candidate_id for candidate_id in identifiers):
            raise ValueError("candidate_id cannot be empty")
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("candidate_id values must be unique")
        if any(not actions for _, actions in candidate_rows):
            raise ValueError("candidate plans cannot be empty")

        cfg = self.config
        if rollout_seeds is None:
            seeds = tuple(cfg.base_seed + index for index in range(cfg.rollouts))
        else:
            seeds = tuple(int(seed) for seed in rollout_seeds)
            if not seeds:
                raise ValueError("rollout_seeds cannot be empty")
            if len(set(seeds)) != len(seeds):
                raise ValueError("rollout_seeds must be unique")

        scores: list[CandidateRolloutScore] = []
        for candidate_id, actions in candidate_rows:
            returns: list[float] = []
            costs: list[float] = []
            violations = 0
            for seed in seeds:
                world = self.world_factory(seed)
                trace = world.rollout(
                    initial_belief,
                    actions,
                    constraints,
                    gamma=cfg.gamma,
                    stress=stress,
                )
                returns.append(trace.discounted_return)
                costs.append(trace.total_cost)
                violations += int(trace.violated)

            ordered_returns = sorted(returns)
            tail_n = max(1, ceil(len(ordered_returns) * cfg.cvar_alpha))
            cvar = fsum(ordered_returns[:tail_n]) / tail_n
            sample_count = len(seeds)
            violation_rate = violations / sample_count
            violation_ucb = _hoeffding_upper_rate(
                violation_rate,
                sample_count,
                cfg.monte_carlo_delta,
            )
            mean_return = fsum(returns) / sample_count
            mean_cost = fsum(costs) / sample_count
            robust_score = cvar - cfg.violation_penalty * violation_ucb
            scores.append(
                CandidateRolloutScore(
                    candidate_id=candidate_id,
                    mean_return=mean_return,
                    cvar_return=cvar,
                    violation_rate=violation_rate,
                    monte_carlo_violation_ucb=violation_ucb,
                    monte_carlo_delta=cfg.monte_carlo_delta,
                    rollout_count=sample_count,
                    mean_cost=mean_cost,
                    robust_score=robust_score,
                    feasible=violation_ucb <= cfg.max_violation_rate,
                )
            )

        return tuple(
            sorted(
                scores,
                key=lambda score: (
                    score.feasible,
                    -score.monte_carlo_violation_ucb,
                    score.robust_score,
                    score.cvar_return,
                    score.mean_return,
                    score.candidate_id,
                ),
                reverse=True,
            )
        )
