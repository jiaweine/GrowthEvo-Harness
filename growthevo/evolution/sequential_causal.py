from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from hashlib import blake2b
import json
from math import ceil, erfc, inf, isfinite, sqrt
from statistics import NormalDist
from typing import Literal, Mapping

from .online_promotion import (
    CanaryCandidate,
    CanaryDecision,
    CanaryObservation,
    CanaryPlan,
    CanarySnapshot,
    CanaryStatus,
    OnlineCanaryMonitor,
    OnlinePromotionController,
)


@dataclass(frozen=True, slots=True)
class FrozenCUPEDSpec:
    """Pre-experiment variance-reduction contract for the primary metric.

    ``theta`` and ``center`` must be estimated from pre-exposure/reference data
    and frozen before online outcomes are inspected. Keeping the transform fixed
    at every group-sequential look avoids the inconsistent-adjustment failure mode
    where the analysis itself changes after seeing interim results.
    """

    covariate_name: str
    theta: float
    center: float
    covariate_min: float
    covariate_max: float
    source_fingerprint: str

    def __post_init__(self) -> None:
        if not self.covariate_name.strip():
            raise ValueError("covariate_name cannot be empty")
        if not self.source_fingerprint.strip():
            raise ValueError("source_fingerprint cannot be empty")
        for name, value in (
            ("theta", self.theta),
            ("center", self.center),
            ("covariate_min", self.covariate_min),
            ("covariate_max", self.covariate_max),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.covariate_max <= self.covariate_min:
            raise ValueError("covariate_max must exceed covariate_min")
        if not self.covariate_min <= self.center <= self.covariate_max:
            raise ValueError("center must lie inside the frozen covariate bounds")

    def adjust(self, outcome: float, covariates: Mapping[str, float]) -> float:
        if not isfinite(outcome):
            raise ValueError("CUPED outcome must be finite")
        if self.covariate_name not in covariates:
            raise ValueError(f"missing frozen CUPED covariate: {self.covariate_name}")
        value = float(covariates[self.covariate_name])
        if not isfinite(value):
            raise ValueError("CUPED covariate must be finite")
        if value < self.covariate_min - 1e-12 or value > self.covariate_max + 1e-12:
            raise ValueError("CUPED covariate is outside pre-registered bounds")
        adjusted = outcome - self.theta * (value - self.center)
        if not isfinite(adjusted):
            raise ValueError("CUPED adjusted outcome must be finite")
        return adjusted

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            {"schema": "growthevo.frozen-cuped.v1", **asdict(self)},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return blake2b(encoded, digest_size=20).hexdigest()


@dataclass(frozen=True, slots=True)
class GroupSequentialSpec:
    """Pre-registered primary-success analysis for the final rollout stage.

    The dependency-free reference implementation uses a small number of planned
    Welch-z looks and conservative alpha spending. Safety/deterioration remains
    on the base anytime-valid e-process; this object is only the *success* gate.
    """

    expected_final_stage_observations: int
    look_fractions: tuple[float, ...] = (0.25, 0.50, 0.75, 1.0)
    alpha: float = 0.05
    spending: Literal["equal", "obrien_fleming"] = "obrien_fleming"
    min_arm_observations: int = 20

    def __post_init__(self) -> None:
        for name, value in (
            ("expected_final_stage_observations", self.expected_final_stage_observations),
            ("min_arm_observations", self.min_arm_observations),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
        if self.expected_final_stage_observations <= 0:
            raise ValueError("expected_final_stage_observations must be positive")
        if not self.look_fractions:
            raise ValueError("look_fractions cannot be empty")
        previous = 0.0
        targets: list[int] = []
        for fraction in self.look_fractions:
            if not isfinite(fraction) or not 0 < fraction <= 1:
                raise ValueError("look fractions must be finite and in (0, 1]")
            if fraction <= previous:
                raise ValueError("look fractions must be strictly increasing")
            previous = fraction
            targets.append(ceil(self.expected_final_stage_observations * fraction))
        if abs(self.look_fractions[-1] - 1.0) > 1e-12:
            raise ValueError("the final group-sequential look must be at fraction 1.0")
        if len(set(targets)) != len(targets):
            raise ValueError("expected sample size is too small for distinct look targets")
        if not isfinite(self.alpha) or not 0 < self.alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if self.spending not in {"equal", "obrien_fleming"}:
            raise ValueError("unsupported group-sequential spending rule")
        if self.spending == "obrien_fleming" and self.alpha >= 0.5:
            raise ValueError("O'Brien-Fleming alpha must be below 0.5")
        if self.min_arm_observations < 2:
            raise ValueError("min_arm_observations must be at least 2")

    @property
    def look_targets(self) -> tuple[int, ...]:
        return tuple(
            ceil(self.expected_final_stage_observations * fraction)
            for fraction in self.look_fractions
        )

    def cumulative_alpha(self, look_index: int) -> float:
        if not 0 <= look_index < len(self.look_fractions):
            raise ValueError("look_index outside pre-registered looks")
        if self.spending == "equal":
            return self.alpha * (look_index + 1) / len(self.look_fractions)
        if look_index == len(self.look_fractions) - 1:
            return self.alpha
        fraction = self.look_fractions[look_index]
        z_alpha = -NormalDist().inv_cdf(self.alpha)
        return 0.5 * erfc(z_alpha / sqrt(2.0 * fraction))

    def incremental_alpha(self, look_index: int) -> float:
        current = self.cumulative_alpha(look_index)
        previous = self.cumulative_alpha(look_index - 1) if look_index else 0.0
        return max(0.0, current - previous)


@dataclass(frozen=True, slots=True)
class HighPowerCanaryPlan:
    """Base canary safety contract plus a stronger pre-registered success gate."""

    base_plan: CanaryPlan
    group_sequential: GroupSequentialSpec
    cuped: FrozenCUPEDSpec | None = None
    analysis_unit_name: str = "user"

    def __post_init__(self) -> None:
        if not self.analysis_unit_name.strip():
            raise ValueError("analysis_unit_name cannot be empty")
        if self.group_sequential.alpha > self.base_plan.promotion_alpha + 1e-12:
            raise ValueError("group-sequential alpha cannot exceed base promotion_alpha")
        if (
            self.group_sequential.expected_final_stage_observations
            < self.base_plan.min_observations_per_stage
        ):
            raise ValueError(
                "expected final-stage observations cannot be below the base stage minimum"
            )

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema": "growthevo.high-power-canary-plan.v3",
            "base_plan": asdict(self.base_plan),
            "group_sequential": asdict(self.group_sequential),
            "cuped": asdict(self.cuped) if self.cuped is not None else None,
            "cuped_fingerprint": self.cuped.fingerprint if self.cuped is not None else None,
            "analysis_unit_name": self.analysis_unit_name,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return blake2b(encoded, digest_size=20).hexdigest()


@dataclass(frozen=True, slots=True)
class HighPowerExposureTicket:
    """Assignment receipt; admitted units retain their first exposure stage."""

    analysis_unit_id: str
    routing_stage_index: int
    in_canary: bool
    assigned_to_challenger: bool
    traffic_fraction: float
    challenger_probability: float


@dataclass(frozen=True, slots=True)
class HighPowerCanaryObservation:
    """One matured cluster/unit outcome tied to its original exposure stage."""

    analysis_unit_id: str
    routing_stage_index: int
    assigned_to_challenger: bool
    assignment_probability: float
    traffic_fraction: float
    metrics: Mapping[str, float]
    covariates: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.analysis_unit_id:
            raise ValueError("analysis_unit_id cannot be empty")
        if self.routing_stage_index < 0:
            raise ValueError("routing_stage_index must be non-negative")
        if not 0 < self.assignment_probability < 1:
            raise ValueError("assignment_probability must be in (0, 1)")
        if not 0 < self.traffic_fraction <= 1:
            raise ValueError("traffic_fraction must be in (0, 1]")
        if not self.metrics:
            raise ValueError("metrics cannot be empty")
        for name, value in self.metrics.items():
            if not name:
                raise ValueError("metric names cannot be empty")
            if not isfinite(float(value)):
                raise ValueError(f"metric {name!r} must be finite")
        for name, value in self.covariates.items():
            if not name:
                raise ValueError("covariate names cannot be empty")
            if not isfinite(float(value)):
                raise ValueError(f"covariate {name!r} must be finite")

    def as_base_observation(self) -> CanaryObservation:
        return CanaryObservation(
            analysis_unit_id=self.analysis_unit_id,
            assigned_to_challenger=self.assigned_to_challenger,
            assignment_probability=self.assignment_probability,
            traffic_fraction=self.traffic_fraction,
            metrics=self.metrics,
        )


@dataclass(slots=True)
class _RunningMoments:
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0

    def update(self, value: float) -> None:
        self.n += 1
        delta = value - self.mean
        self.mean += delta / self.n
        self.m2 += delta * (value - self.mean)

    @property
    def variance(self) -> float:
        return self.m2 / (self.n - 1) if self.n > 1 else float("nan")


@dataclass(frozen=True, slots=True)
class GroupSequentialLook:
    look_index: int
    information_fraction: float
    target_observations: int
    observed: int
    challenger_observations: int
    control_observations: int
    effect_estimate: float
    standard_error: float
    z_score: float
    one_sided_p_value: float
    incremental_alpha: float
    cumulative_alpha: float
    success: bool
    sufficient_arm_counts: bool


@dataclass(frozen=True, slots=True)
class GroupSequentialEvidence:
    success: bool
    exhausted: bool
    observations: int
    next_target: int | None
    cuped_enabled: bool
    looks: tuple[GroupSequentialLook, ...]


class GroupSequentialPrimaryMonitor:
    """Final-stage primary gate with optional *frozen* CUPED adjustment.

    This is an asymptotic Welch-z reference implementation. It deliberately
    analyzes only at pre-registered looks. Per-look alpha allocations sum to at
    most the configured family alpha, so the reference remains conservative even
    without a multivariate-normal boundary dependency.
    """

    def __init__(self, plan: HighPowerCanaryPlan) -> None:
        self.plan = plan
        self.spec = plan.group_sequential
        metric_by_name = {metric.name: metric for metric in plan.base_plan.metrics}
        self.metric = metric_by_name[plan.base_plan.primary_metric]
        self.challenger = _RunningMoments()
        self.control = _RunningMoments()
        self._observations = 0
        self._next_look = 0
        self._looks: list[GroupSequentialLook] = []
        self._success = False

    def _adjusted_oriented_value(self, observation: HighPowerCanaryObservation) -> float:
        raw = float(observation.metrics[self.metric.name])
        if not isfinite(raw):
            raise ValueError("primary metric must be finite")
        if raw < self.metric.outcome_min - 1e-12 or raw > self.metric.outcome_max + 1e-12:
            raise ValueError("primary metric is outside pre-registered outcome bounds")
        adjusted = (
            self.plan.cuped.adjust(raw, observation.covariates)
            if self.plan.cuped is not None
            else raw
        )
        return adjusted if self.metric.higher_is_better else -adjusted

    def _updated_moments(self, observation: HighPowerCanaryObservation) -> _RunningMoments:
        if self._next_look >= len(self.spec.look_targets):
            raise RuntimeError("primary analysis has consumed its final planned look")
        value = self._adjusted_oriented_value(observation)
        target = replace(self.challenger if observation.assigned_to_challenger else self.control)
        target.update(value)
        challenger = target if observation.assigned_to_challenger else self.challenger
        control = self.control if observation.assigned_to_challenger else target
        if not all(isfinite(item) for item in (
            target.mean, target.m2, challenger.mean - control.mean,
        )):
            raise ValueError("primary running moments and effect must remain finite")
        return target

    def validate_observation(self, observation: HighPowerCanaryObservation) -> None:
        self._updated_moments(observation)

    def observe(self, observation: HighPowerCanaryObservation) -> GroupSequentialEvidence:
        target = self._updated_moments(observation)
        if observation.assigned_to_challenger:
            self.challenger = target
        else:
            self.control = target
        self._observations += 1

        if self._next_look < len(self.spec.look_targets):
            look_target = self.spec.look_targets[self._next_look]
            if self._observations >= look_target:
                self._evaluate_look(self._next_look)
                self._next_look += 1
        return self.evidence()

    def _evaluate_look(self, look_index: int) -> None:
        enough = (
            self.challenger.n >= self.spec.min_arm_observations
            and self.control.n >= self.spec.min_arm_observations
        )
        estimate = self.challenger.mean - self.control.mean
        standard_error = inf
        z_score = float("-inf")
        p_value = 1.0
        if enough:
            standard_error = sqrt(
                self.challenger.variance / self.challenger.n
                + self.control.variance / self.control.n
            )
            null = self.plan.base_plan.primary_min_improvement
            if standard_error == 0.0:
                z_score = inf if estimate > null else float("-inf")
            else:
                z_score = (estimate - null) / standard_error
            p_value = 0.5 * erfc(z_score / sqrt(2.0))

        alpha = self.spec.incremental_alpha(look_index)
        success = bool(enough and alpha > 0.0 and p_value <= alpha)
        # Each look earns its own decision. An earlier primary crossing cannot
        # bypass a later look if the joint safety gate previously kept us running.
        self._success = success
        self._looks.append(
            GroupSequentialLook(
                look_index=look_index,
                information_fraction=self.spec.look_fractions[look_index],
                target_observations=self.spec.look_targets[look_index],
                observed=self._observations,
                challenger_observations=self.challenger.n,
                control_observations=self.control.n,
                effect_estimate=estimate,
                standard_error=standard_error,
                z_score=z_score,
                one_sided_p_value=p_value,
                incremental_alpha=alpha,
                cumulative_alpha=self.spec.cumulative_alpha(look_index),
                success=success,
                sufficient_arm_counts=enough,
            )
        )

    @property
    def success(self) -> bool:
        return self._success

    @property
    def exhausted(self) -> bool:
        return self._next_look >= len(self.spec.look_targets) and not self._success

    def evidence(self) -> GroupSequentialEvidence:
        next_target = (
            self.spec.look_targets[self._next_look]
            if self._next_look < len(self.spec.look_targets)
            else None
        )
        return GroupSequentialEvidence(
            success=self._success,
            exhausted=self.exhausted,
            observations=self._observations,
            next_target=next_target,
            cuped_enabled=self.plan.cuped is not None,
            looks=tuple(self._looks),
        )


class HighPowerOnlineCanaryMonitor(OnlineCanaryMonitor):
    """Canary monitor with delayed-outcome hygiene and a planned primary gate."""

    def __init__(self, plan: HighPowerCanaryPlan) -> None:
        super().__init__(plan.base_plan)
        self.high_power_plan = plan
        self.primary_group_sequential = GroupSequentialPrimaryMonitor(plan)
        self._stage_matured_counts = [0 for _ in self.plan.stages]

    def snapshot(
        self,
        decision: CanaryDecision = CanaryDecision.HOLD,
        reasons: tuple[str, ...] = (),
    ) -> CanarySnapshot:
        return CanarySnapshot(
            status=self.status,
            decision=decision,
            stage_index=self.stage_index,
            traffic_fraction=self.traffic_fraction,
            total_observations=self._total_observations,
            stage_observations=self._stage_matured_counts[self.stage_index],
            challenger_observations=self._challenger_observations,
            cumulative_challenger_cost=self._cumulative_challenger_cost,
            metric_evidence=tuple(
                self._monitors[name].evidence()
                for name in sorted(self._monitors)
            ),
            reasons=reasons,
        )

    def _preflight_observation(
        self, observation: HighPowerCanaryObservation,
    ) -> HighPowerCanaryObservation:
        observation = replace(
            observation,
            metrics=self._validated_metrics(observation.metrics),
            covariates={name: float(value) for name, value in observation.covariates.items()},
        )
        final_stage_index = len(self.plan.stages) - 1
        if observation.routing_stage_index == final_stage_index:
            self.primary_group_sequential.validate_observation(observation)
        return observation

    def observe(self, observation: HighPowerCanaryObservation) -> CanarySnapshot:
        if self.status is not CanaryStatus.RUNNING:
            raise RuntimeError("canary observations require RUNNING status")
        if observation.routing_stage_index >= len(self.plan.stages):
            raise ValueError("routing_stage_index is outside pre-registered stages")
        if observation.routing_stage_index > self.stage_index:
            raise ValueError("outcome cannot arrive from a future rollout stage")
        unit_token = self._unit_token(observation.analysis_unit_id)
        if unit_token in self._seen_unit_tokens:
            raise ValueError("analysis_unit_id has already been observed")
        if abs(observation.assignment_probability - self.plan.challenger_probability) > 1e-12:
            raise ValueError("observation assignment probability differs from canary plan")
        expected_traffic = self.plan.stages[observation.routing_stage_index]
        if abs(observation.traffic_fraction - expected_traffic) > 1e-12:
            raise ValueError("observation traffic fraction differs from routing stage")
        observation = self._preflight_observation(observation)

        self._seen_unit_tokens.add(unit_token)
        self._total_observations += 1
        self._stage_matured_counts[observation.routing_stage_index] += 1
        if observation.assigned_to_challenger:
            self._challenger_observations += 1
            if self.plan.cumulative_cost_metric is not None:
                self._cumulative_challenger_cost += float(
                    observation.metrics[self.plan.cumulative_cost_metric]
                )

        base_observation = observation.as_base_observation()
        for monitor in self._monitors.values():
            monitor.update(
                base_observation,
                plan=self.plan,
                update_superiority=False,
            )

        final_stage_index = len(self.plan.stages) - 1
        previous_looks = len(self.primary_group_sequential.evidence().looks)
        if observation.routing_stage_index == final_stage_index:
            self.primary_group_sequential.observe(observation)
        primary = self.primary_group_sequential.evidence()
        new_primary_look = len(primary.looks) > previous_looks

        rollback_reasons = self._rollback_reasons()
        if rollback_reasons:
            self.status = CanaryStatus.ROLLED_BACK
            return self.snapshot(CanaryDecision.ROLLBACK, tuple(rollback_reasons))

        if self._stage_matured_counts[self.stage_index] < self.plan.min_observations_per_stage:
            return self.snapshot(
                CanaryDecision.HOLD,
                ("minimum_current_stage_matured_observations_not_reached",),
            )

        if self.stage_index == final_stage_index:
            if primary.exhausted:
                self.status = CanaryStatus.ROLLED_BACK
                return self.snapshot(
                    CanaryDecision.ROLLBACK,
                    ("group_sequential_primary_exhausted_without_superiority",),
                )
            safe, reasons = self._safe_to_ramp()
            if new_primary_look and primary.success and safe:
                self.status = CanaryStatus.PROMOTED
                return self.snapshot(
                    CanaryDecision.PROMOTE,
                    ("planned_group_sequential_primary_gate_passed",),
                )
            if primary.next_target is None:
                self.status = CanaryStatus.ROLLED_BACK
                return self.snapshot(
                    CanaryDecision.ROLLBACK,
                    ("group_sequential_final_safety_gates_not_established", *reasons),
                )
            if not safe:
                return self.snapshot(CanaryDecision.HOLD, reasons)
            return self.snapshot(
                CanaryDecision.HOLD,
                ("waiting_for_planned_group_sequential_primary_look",),
            )

        safe, reasons = self._safe_to_ramp()
        if not safe:
            return self.snapshot(CanaryDecision.HOLD, reasons)
        self.stage_index += 1
        return self.snapshot(CanaryDecision.ADVANCE, ("stage_safety_established",))


class HighPowerOnlinePromotionController(OnlinePromotionController):
    """Champion/challenger controller with frozen CUPED and delayed-outcome tickets."""

    def __init__(
        self,
        *,
        champion_name: str,
        candidate: CanaryCandidate,
        plan: HighPowerCanaryPlan,
    ) -> None:
        super().__init__(
            champion_name=champion_name,
            candidate=candidate,
            plan=plan.base_plan,
        )
        self.high_power_plan = plan
        self.monitor = HighPowerOnlineCanaryMonitor(plan)
        # Keep the first admitted stage for the controller's lifetime, including
        # after maturation. Tokens share the monitor's plan-scoped dedupe identity;
        # raw analysis-unit IDs are not retained in this registry or audit events.
        self._exposure_stages: dict[bytes, int] = {}
        self._append(
            "high_power_inference_registered",
            {
                "high_power_plan_fingerprint": plan.fingerprint,
                "group_sequential": asdict(plan.group_sequential),
                "cuped_fingerprint": (
                    plan.cuped.fingerprint if plan.cuped is not None else None
                ),
                "analysis_unit_name": plan.analysis_unit_name,
            },
        )

    def start(self) -> CanarySnapshot:
        snapshot = self.monitor.start()
        self._append("canary_started", self._high_power_snapshot_payload(snapshot))
        return snapshot

    def enroll(self, analysis_unit_id: str) -> HighPowerExposureTicket:
        if self.monitor.status is not CanaryStatus.RUNNING:
            raise RuntimeError("routing requires a running canary")
        unit_token = self.monitor._unit_token(analysis_unit_id)
        stage_index = self._exposure_stages.get(unit_token, self.monitor.stage_index)
        route = self.router.route(analysis_unit_id, stage_index=stage_index)
        if route.in_canary:
            self._exposure_stages[unit_token] = stage_index
        return HighPowerExposureTicket(
            analysis_unit_id=analysis_unit_id,
            routing_stage_index=stage_index,
            in_canary=route.in_canary,
            assigned_to_challenger=route.assigned_to_challenger,
            traffic_fraction=route.traffic_fraction,
            challenger_probability=route.challenger_probability,
        )

    def route(self, analysis_unit_id: str) -> HighPowerExposureTicket:
        return self.enroll(analysis_unit_id)

    def _high_power_snapshot_payload(self, snapshot: CanarySnapshot) -> dict[str, object]:
        payload = self._snapshot_payload(snapshot)
        evidence = self.monitor.primary_group_sequential.evidence()
        payload["high_power_plan_fingerprint"] = self.high_power_plan.fingerprint
        payload["group_sequential_primary"] = asdict(evidence)
        return payload

    def observe(self, observation: HighPowerCanaryObservation) -> CanarySnapshot:
        if self.monitor.status is not CanaryStatus.RUNNING:
            raise RuntimeError("canary observations require RUNNING status")
        if observation.routing_stage_index > self.monitor.stage_index:
            raise ValueError("outcome cannot reference a future rollout stage")
        unit_token = self.monitor._unit_token(observation.analysis_unit_id)
        registered_stage = self._exposure_stages.get(unit_token)
        if registered_stage is None:
            raise ValueError("analysis unit has no registered exposure; call enroll first")
        if observation.routing_stage_index != registered_stage:
            raise ValueError("outcome does not match the registered exposure stage")
        expected_route = self.router.route(
            observation.analysis_unit_id,
            stage_index=registered_stage,
        )
        if not expected_route.in_canary:
            raise ValueError("analysis unit was not admitted by its exposure stage")
        if observation.assigned_to_challenger != expected_route.assigned_to_challenger:
            raise ValueError("observed arm does not match the pre-registered stable router")
        if abs(observation.traffic_fraction - expected_route.traffic_fraction) > 1e-12:
            raise ValueError("observation traffic fraction differs from exposure ticket")
        if (
            abs(observation.assignment_probability - expected_route.challenger_probability)
            > 1e-12
        ):
            raise ValueError("observation propensity differs from exposure ticket")

        snapshot = self.monitor.observe(observation)
        if snapshot.decision in {
            CanaryDecision.ADVANCE,
            CanaryDecision.ROLLBACK,
            CanaryDecision.PROMOTE,
        }:
            kind = {
                CanaryDecision.ADVANCE: "canary_stage_advanced",
                CanaryDecision.ROLLBACK: "challenger_rolled_back",
                CanaryDecision.PROMOTE: "challenger_promoted",
            }[snapshot.decision]
            self._append(kind, self._high_power_snapshot_payload(snapshot))
        if snapshot.decision is CanaryDecision.PROMOTE:
            self.champion_name = self.candidate.name
        return snapshot
