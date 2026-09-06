from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from hashlib import blake2b, sha256
import json
from math import exp, isfinite, log
from typing import Any, Mapping, Sequence

from growthevo.bench.llm_evaluation import LockedLLMBenchmarkArtifact


class CanaryStatus(str, Enum):
    REGISTERED = "registered"
    RUNNING = "running"
    ROLLED_BACK = "rolled_back"
    PROMOTED = "promoted"


class CanaryDecision(str, Enum):
    HOLD = "hold"
    ADVANCE = "advance"
    ROLLBACK = "rollback"
    PROMOTE = "promote"


@dataclass(frozen=True, slots=True)
class CanaryCandidate:
    """One locked-holdout-qualified model+harness challenger."""

    name: str
    provider: str
    model: str
    contract_fingerprint: str
    source_commit_sha: str
    source_test_fingerprint: str
    source_evidence_manifest_fingerprint: str
    promotion_artifact_fingerprint: str

    @classmethod
    def from_locked_artifact(
        cls,
        artifact: LockedLLMBenchmarkArtifact,
    ) -> "CanaryCandidate":
        if not artifact.promotion_eligible:
            raise ValueError("locked artifact is not promotion eligible")
        metrics = dict(artifact.metrics)
        provider = str(metrics.get("provider", ""))
        model = str(metrics.get("model", ""))
        contract = str(metrics.get("contract_fingerprint", ""))
        evidence_manifest = str(metrics.get("evidence_manifest_fingerprint", ""))
        for field_name, value in (
            ("provider", provider),
            ("model", model),
            ("contract_fingerprint", contract),
            ("evidence_manifest_fingerprint", evidence_manifest),
        ):
            if not value:
                raise ValueError(f"promotion artifact lacks {field_name}")
        artifact_fingerprint = sha256(artifact.to_json().encode("utf-8")).hexdigest()
        return cls(
            name=artifact.selected_candidate,
            provider=provider,
            model=model,
            contract_fingerprint=contract,
            source_commit_sha=artifact.commit_sha,
            source_test_fingerprint=artifact.test_fingerprint,
            source_evidence_manifest_fingerprint=evidence_manifest,
            promotion_artifact_fingerprint=artifact_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class CanaryMetricSpec:
    """Bounded randomized metric with relative and optional absolute safety gates.

    Every treatment-control contrast is oriented so that positive means the
    challenger is better. ``noninferiority_margin`` is the largest tolerated
    deterioration on that oriented scale. Optional absolute bounds apply to the
    challenger-arm mean and are useful for spend, fatigue, churn, error rate,
    latency, or other hard operational guardrails.
    """

    name: str
    outcome_min: float
    outcome_max: float
    higher_is_better: bool = True
    noninferiority_margin: float = 0.0
    absolute_min: float | None = None
    absolute_max: float | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("metric name cannot be empty")
        for field_name, value in (
            ("outcome_min", self.outcome_min),
            ("outcome_max", self.outcome_max),
            ("noninferiority_margin", self.noninferiority_margin),
        ):
            if not isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if self.outcome_max <= self.outcome_min:
            raise ValueError("outcome_max must be greater than outcome_min")
        if self.noninferiority_margin < 0:
            raise ValueError("noninferiority_margin must be non-negative")
        if self.absolute_min is not None:
            if not isfinite(self.absolute_min):
                raise ValueError("absolute_min must be finite")
            if not self.outcome_min <= self.absolute_min <= self.outcome_max:
                raise ValueError("absolute_min must lie inside the outcome bounds")
        if self.absolute_max is not None:
            if not isfinite(self.absolute_max):
                raise ValueError("absolute_max must be finite")
            if not self.outcome_min <= self.absolute_max <= self.outcome_max:
                raise ValueError("absolute_max must lie inside the outcome bounds")
        if (
            self.absolute_min is not None
            and self.absolute_max is not None
            and self.absolute_min >= self.absolute_max
        ):
            raise ValueError("absolute_min must be below absolute_max")


@dataclass(frozen=True, slots=True)
class CanaryPlan:
    """Pre-registered online rollout and sequential-testing contract."""

    experiment_id: str
    candidate_name: str
    candidate_contract_fingerprint: str
    source_artifact_fingerprint: str
    metrics: tuple[CanaryMetricSpec, ...]
    primary_metric: str
    stages: tuple[float, ...] = (0.01, 0.05, 0.10, 0.25)
    challenger_probability: float = 0.50
    min_observations_per_stage: int = 200
    primary_min_improvement: float = 0.0
    ramp_alpha: float = 0.05
    promotion_alpha: float = 0.05
    rollback_family_alpha: float = 0.01
    e_bet_grid: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 4.0)
    routing_salt: str = "growthevo-canary-v1"
    cumulative_cost_metric: str | None = None
    max_challenger_cumulative_cost: float | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("experiment_id", self.experiment_id),
            ("candidate_name", self.candidate_name),
            ("candidate_contract_fingerprint", self.candidate_contract_fingerprint),
            ("source_artifact_fingerprint", self.source_artifact_fingerprint),
            ("primary_metric", self.primary_metric),
            ("routing_salt", self.routing_salt),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if not self.metrics:
            raise ValueError("at least one canary metric is required")
        metric_names = [metric.name for metric in self.metrics]
        if len(set(metric_names)) != len(metric_names):
            raise ValueError("canary metric names must be unique")
        if self.primary_metric not in set(metric_names):
            raise ValueError("primary_metric must reference a declared metric")
        if not self.stages:
            raise ValueError("at least one rollout stage is required")
        previous = 0.0
        for stage in self.stages:
            if not isfinite(stage) or not 0 < stage <= 1:
                raise ValueError("rollout stages must be finite and in (0, 1]")
            if stage <= previous:
                raise ValueError("rollout stages must be strictly increasing")
            previous = stage
        if not 0 < self.challenger_probability < 1:
            raise ValueError("challenger_probability must be in (0, 1)")
        if self.min_observations_per_stage <= 0:
            raise ValueError("min_observations_per_stage must be positive")
        if not isfinite(self.primary_min_improvement):
            raise ValueError("primary_min_improvement must be finite")
        for field_name, alpha in (
            ("ramp_alpha", self.ramp_alpha),
            ("promotion_alpha", self.promotion_alpha),
            ("rollback_family_alpha", self.rollback_family_alpha),
        ):
            if not isfinite(alpha) or not 0 < alpha < 1:
                raise ValueError(f"{field_name} must be in (0, 1)")
        if not self.e_bet_grid:
            raise ValueError("e_bet_grid cannot be empty")
        for bet in self.e_bet_grid:
            if not isfinite(bet) or bet <= 0:
                raise ValueError("e_bet_grid values must be positive and finite")
        metric_by_name = {metric.name: metric for metric in self.metrics}
        if self.max_challenger_cumulative_cost is not None:
            if (
                not isfinite(self.max_challenger_cumulative_cost)
                or self.max_challenger_cumulative_cost < 0
            ):
                raise ValueError("max_challenger_cumulative_cost must be non-negative")
            if self.cumulative_cost_metric is None:
                raise ValueError("cumulative_cost_metric is required with a cost cap")
        if self.cumulative_cost_metric is not None:
            if self.cumulative_cost_metric not in metric_by_name:
                raise ValueError("cumulative_cost_metric must reference a declared metric")
            if metric_by_name[self.cumulative_cost_metric].outcome_min < 0:
                raise ValueError("cumulative cost metric must be non-negative")

    @property
    def fingerprint(self) -> str:
        payload = {"schema": "growthevo.online-canary-plan.v1", **asdict(self)}
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return blake2b(encoded, digest_size=20).hexdigest()


@dataclass(frozen=True, slots=True)
class CanaryRoute:
    analysis_unit_id: str
    in_canary: bool
    assigned_to_challenger: bool
    traffic_fraction: float
    challenger_probability: float


class CanaryRouter:
    """Stable two-hash routing for monotonic staged exposure and fixed arms."""

    def __init__(self, plan: CanaryPlan) -> None:
        self.plan = plan

    def _uniform(self, analysis_unit_id: str, namespace: str) -> float:
        if not analysis_unit_id:
            raise ValueError("analysis_unit_id cannot be empty")
        material = (
            f"{self.plan.routing_salt}|{self.plan.experiment_id}|"
            f"{namespace}|{analysis_unit_id}"
        ).encode("utf-8")
        integer = int.from_bytes(blake2b(material, digest_size=8).digest(), "big")
        return integer / float(1 << 64)

    def route(self, analysis_unit_id: str, *, stage_index: int) -> CanaryRoute:
        if not 0 <= stage_index < len(self.plan.stages):
            raise ValueError("stage_index is outside the pre-registered rollout stages")
        traffic = self.plan.stages[stage_index]
        in_canary = self._uniform(analysis_unit_id, "inclusion") < traffic
        challenger = False
        if in_canary:
            challenger = (
                self._uniform(analysis_unit_id, "arm")
                < self.plan.challenger_probability
            )
        return CanaryRoute(
            analysis_unit_id=analysis_unit_id,
            in_canary=in_canary,
            assigned_to_challenger=challenger,
            traffic_fraction=traffic,
            challenger_probability=self.plan.challenger_probability,
        )


@dataclass(frozen=True, slots=True)
class CanaryObservation:
    """One matured bounded outcome for one unique randomized analysis unit."""

    analysis_unit_id: str
    assigned_to_challenger: bool
    assignment_probability: float
    traffic_fraction: float
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        if not self.analysis_unit_id:
            raise ValueError("analysis_unit_id cannot be empty")
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


class HoeffdingMixtureEProcess:
    """Anytime-valid bounded-mean e-process with a pre-registered bet mixture.

    For X_t in [a_t, b_t], under H0: E[X_t | F_(t-1)] <= mu_t,
    Hoeffding's lemma makes each fixed positive betting component

        exp(sum eta*(X_t-mu_t)/(b_t-a_t) - eta^2/8)

    a non-negative supermartingale. A convex mixture remains an e-process, so a
    threshold may be monitored continuously without the repeated-peeking failure
    of a fixed-horizon z/t test.
    """

    def __init__(self, bets: Sequence[float]) -> None:
        if not bets:
            raise ValueError("at least one e-process bet is required")
        self._bets = tuple(float(value) for value in bets)
        if any(not isfinite(value) or value <= 0 for value in self._bets):
            raise ValueError("e-process bets must be positive and finite")
        self._logs = [0.0 for _ in self._bets]
        self._log_weight = -log(len(self._bets))
        self._observations = 0
        self._max_e = 1.0

    @staticmethod
    def _logsumexp(values: Sequence[float]) -> float:
        maximum = max(values)
        if maximum == float("inf"):
            return maximum
        return maximum + log(sum(exp(value - maximum) for value in values))

    @staticmethod
    def _exp(value: float) -> float:
        return float("inf") if value >= 709.0 else exp(value)

    def update_upper_null(
        self,
        value: float,
        *,
        null_upper: float,
        lower: float,
        upper: float,
    ) -> float:
        for field_name, item in (
            ("value", value),
            ("null_upper", null_upper),
            ("lower", lower),
            ("upper", upper),
        ):
            if not isfinite(item):
                raise ValueError(f"{field_name} must be finite")
        if upper <= lower:
            raise ValueError("upper must exceed lower")
        if value < lower - 1e-12 or value > upper + 1e-12:
            raise ValueError("value lies outside its pre-registered bounds")
        standardized = (value - null_upper) / (upper - lower)
        for index, eta in enumerate(self._bets):
            self._logs[index] += eta * standardized - eta * eta / 8.0
        self._observations += 1
        current = self.e_value
        self._max_e = max(self._max_e, current)
        return current

    def update_lower_null(
        self,
        value: float,
        *,
        null_lower: float,
        lower: float,
        upper: float,
    ) -> float:
        return self.update_upper_null(
            -value,
            null_upper=-null_lower,
            lower=-upper,
            upper=-lower,
        )

    @property
    def e_value(self) -> float:
        logs = [self._log_weight + value for value in self._logs]
        return self._exp(self._logsumexp(logs))

    @property
    def max_e_value(self) -> float:
        return self._max_e

    @property
    def observations(self) -> int:
        return self._observations


def _oriented_ht_contribution(
    *,
    value: float,
    assigned_to_challenger: bool,
    challenger_probability: float,
    spec: CanaryMetricSpec,
) -> tuple[float, float, float]:
    if value < spec.outcome_min - 1e-12 or value > spec.outcome_max + 1e-12:
        raise ValueError(f"metric {spec.name!r} is outside pre-registered outcome bounds")
    p = challenger_probability
    raw = value / p if assigned_to_challenger else -value / (1.0 - p)
    bound_candidates = (
        spec.outcome_min / p,
        spec.outcome_max / p,
        -spec.outcome_min / (1.0 - p),
        -spec.outcome_max / (1.0 - p),
    )
    raw_lower = min(bound_candidates)
    raw_upper = max(bound_candidates)
    if spec.higher_is_better:
        return raw, raw_lower, raw_upper
    return -raw, -raw_upper, -raw_lower


@dataclass(frozen=True, slots=True)
class MetricSequentialEvidence:
    name: str
    relative_noninferiority_e: float
    relative_noninferiority_max_e: float
    relative_harm_e: float
    relative_harm_max_e: float
    primary_superiority_e: float | None
    primary_superiority_max_e: float | None
    absolute_min_safe_e: float | None
    absolute_min_violation_e: float | None
    absolute_max_safe_e: float | None
    absolute_max_violation_e: float | None
    challenger_observations: int


class _MetricMonitor:
    def __init__(self, spec: CanaryMetricSpec, plan: CanaryPlan) -> None:
        self.spec = spec
        bets = plan.e_bet_grid
        self.noninferiority = HoeffdingMixtureEProcess(bets)
        self.harm = HoeffdingMixtureEProcess(bets)
        self.superiority = (
            HoeffdingMixtureEProcess(bets)
            if spec.name == plan.primary_metric
            else None
        )
        self.absolute_min_safe = (
            HoeffdingMixtureEProcess(bets) if spec.absolute_min is not None else None
        )
        self.absolute_min_violation = (
            HoeffdingMixtureEProcess(bets) if spec.absolute_min is not None else None
        )
        self.absolute_max_safe = (
            HoeffdingMixtureEProcess(bets) if spec.absolute_max is not None else None
        )
        self.absolute_max_violation = (
            HoeffdingMixtureEProcess(bets) if spec.absolute_max is not None else None
        )
        self.challenger_observations = 0

    def update(
        self,
        observation: CanaryObservation,
        *,
        plan: CanaryPlan,
        update_superiority: bool,
    ) -> None:
        raw_value = float(observation.metrics[self.spec.name])
        contribution, lower, upper = _oriented_ht_contribution(
            value=raw_value,
            assigned_to_challenger=observation.assigned_to_challenger,
            challenger_probability=observation.assignment_probability,
            spec=self.spec,
        )
        margin = self.spec.noninferiority_margin
        self.noninferiority.update_upper_null(
            contribution,
            null_upper=-margin,
            lower=lower,
            upper=upper,
        )
        self.harm.update_lower_null(
            contribution,
            null_lower=-margin,
            lower=lower,
            upper=upper,
        )
        if self.superiority is not None and update_superiority:
            self.superiority.update_upper_null(
                contribution,
                null_upper=plan.primary_min_improvement,
                lower=lower,
                upper=upper,
            )

        if not observation.assigned_to_challenger:
            return
        self.challenger_observations += 1
        if self.absolute_min_safe is not None and self.spec.absolute_min is not None:
            self.absolute_min_safe.update_upper_null(
                raw_value,
                null_upper=self.spec.absolute_min,
                lower=self.spec.outcome_min,
                upper=self.spec.outcome_max,
            )
            assert self.absolute_min_violation is not None
            self.absolute_min_violation.update_lower_null(
                raw_value,
                null_lower=self.spec.absolute_min,
                lower=self.spec.outcome_min,
                upper=self.spec.outcome_max,
            )
        if self.absolute_max_safe is not None and self.spec.absolute_max is not None:
            self.absolute_max_safe.update_lower_null(
                raw_value,
                null_lower=self.spec.absolute_max,
                lower=self.spec.outcome_min,
                upper=self.spec.outcome_max,
            )
            assert self.absolute_max_violation is not None
            self.absolute_max_violation.update_upper_null(
                raw_value,
                null_upper=self.spec.absolute_max,
                lower=self.spec.outcome_min,
                upper=self.spec.outcome_max,
            )

    def evidence(self) -> MetricSequentialEvidence:
        return MetricSequentialEvidence(
            name=self.spec.name,
            relative_noninferiority_e=self.noninferiority.e_value,
            relative_noninferiority_max_e=self.noninferiority.max_e_value,
            relative_harm_e=self.harm.e_value,
            relative_harm_max_e=self.harm.max_e_value,
            primary_superiority_e=(
                self.superiority.e_value if self.superiority is not None else None
            ),
            primary_superiority_max_e=(
                self.superiority.max_e_value if self.superiority is not None else None
            ),
            absolute_min_safe_e=(
                self.absolute_min_safe.e_value
                if self.absolute_min_safe is not None
                else None
            ),
            absolute_min_violation_e=(
                self.absolute_min_violation.max_e_value
                if self.absolute_min_violation is not None
                else None
            ),
            absolute_max_safe_e=(
                self.absolute_max_safe.e_value
                if self.absolute_max_safe is not None
                else None
            ),
            absolute_max_violation_e=(
                self.absolute_max_violation.max_e_value
                if self.absolute_max_violation is not None
                else None
            ),
            challenger_observations=self.challenger_observations,
        )


@dataclass(frozen=True, slots=True)
class CanarySnapshot:
    status: CanaryStatus
    decision: CanaryDecision
    stage_index: int
    traffic_fraction: float
    total_observations: int
    stage_observations: int
    challenger_observations: int
    cumulative_challenger_cost: float
    metric_evidence: tuple[MetricSequentialEvidence, ...]
    reasons: tuple[str, ...]


class OnlineCanaryMonitor:
    """Fail-closed staged randomized canary with anytime-valid sequential gates."""

    def __init__(self, plan: CanaryPlan) -> None:
        self.plan = plan
        self.status = CanaryStatus.REGISTERED
        self.stage_index = 0
        self._stage_start_observations = 0
        self._seen_unit_tokens: set[bytes] = set()
        self._total_observations = 0
        self._challenger_observations = 0
        self._cumulative_challenger_cost = 0.0
        self._monitors = {
            spec.name: _MetricMonitor(spec, plan)
            for spec in plan.metrics
        }

    def start(self) -> CanarySnapshot:
        if self.status is not CanaryStatus.REGISTERED:
            raise RuntimeError("canary can only be started once")
        self.status = CanaryStatus.RUNNING
        return self.snapshot(CanaryDecision.HOLD, ("canary_started",))

    @property
    def traffic_fraction(self) -> float:
        return self.plan.stages[self.stage_index]

    def _unit_token(self, analysis_unit_id: str) -> bytes:
        material = f"{self.plan.experiment_id}|{analysis_unit_id}".encode("utf-8")
        return blake2b(material, digest_size=16).digest()

    def _harm_test_count(self) -> int:
        count = len(self.plan.metrics)
        for spec in self.plan.metrics:
            count += int(spec.absolute_min is not None)
            count += int(spec.absolute_max is not None)
        return count

    def _rollback_reasons(self) -> list[str]:
        threshold = self._harm_test_count() / self.plan.rollback_family_alpha
        reasons: list[str] = []
        for spec in self.plan.metrics:
            evidence = self._monitors[spec.name].evidence()
            if evidence.relative_harm_max_e >= threshold:
                reasons.append(f"{spec.name}:relative_harm_anytime_e")
            if (
                evidence.absolute_min_violation_e is not None
                and evidence.absolute_min_violation_e >= threshold
            ):
                reasons.append(f"{spec.name}:absolute_min_violation_anytime_e")
            if (
                evidence.absolute_max_violation_e is not None
                and evidence.absolute_max_violation_e >= threshold
            ):
                reasons.append(f"{spec.name}:absolute_max_violation_anytime_e")
        if (
            self.plan.max_challenger_cumulative_cost is not None
            and self._cumulative_challenger_cost
            > self.plan.max_challenger_cumulative_cost + 1e-12
        ):
            reasons.append("challenger_cumulative_cost_cap_exceeded")
        return reasons

    def _safe_to_ramp(self) -> tuple[bool, tuple[str, ...]]:
        threshold = 1.0 / self.plan.ramp_alpha
        gaps: list[str] = []
        for spec in self.plan.metrics:
            evidence = self._monitors[spec.name].evidence()
            if evidence.relative_noninferiority_e < threshold:
                gaps.append(f"{spec.name}:relative_noninferiority_not_established")
            if (
                evidence.absolute_min_safe_e is not None
                and evidence.absolute_min_safe_e < threshold
            ):
                gaps.append(f"{spec.name}:absolute_min_safety_not_established")
            if (
                evidence.absolute_max_safe_e is not None
                and evidence.absolute_max_safe_e < threshold
            ):
                gaps.append(f"{spec.name}:absolute_max_safety_not_established")
        return not gaps, tuple(gaps)

    def _promotion_ready(self) -> tuple[bool, tuple[str, ...]]:
        safe, reasons = self._safe_to_ramp()
        if not safe:
            return False, reasons
        primary = self._monitors[self.plan.primary_metric].evidence()
        threshold = 1.0 / self.plan.promotion_alpha
        if (
            primary.primary_superiority_e is None
            or primary.primary_superiority_e < threshold
        ):
            return False, ("primary_superiority_not_established",)
        return True, ()

    def _validated_metrics(self, metrics: Mapping[str, float]) -> dict[str, float]:
        expected_metrics = {metric.name for metric in self.plan.metrics}
        if set(metrics) != expected_metrics:
            missing = sorted(expected_metrics.difference(metrics))
            unexpected = sorted(set(metrics).difference(expected_metrics))
            raise ValueError(
                f"observation metrics do not match plan; missing={missing}, unexpected={unexpected}"
            )
        values = {name: float(value) for name, value in metrics.items()}
        for metric in self.plan.metrics:
            value = values[metric.name]
            if not isfinite(value):
                raise ValueError(f"metric {metric.name!r} must be finite")
            if value < metric.outcome_min - 1e-12 or value > metric.outcome_max + 1e-12:
                raise ValueError(
                    f"metric {metric.name!r} is outside pre-registered outcome bounds"
                )
        return values

    def observe(self, observation: CanaryObservation) -> CanarySnapshot:
        if self.status is not CanaryStatus.RUNNING:
            raise RuntimeError("canary observations require RUNNING status")
        unit_token = self._unit_token(observation.analysis_unit_id)
        if unit_token in self._seen_unit_tokens:
            raise ValueError("analysis_unit_id has already been observed")
        if abs(observation.assignment_probability - self.plan.challenger_probability) > 1e-12:
            raise ValueError("observation assignment probability differs from canary plan")
        if abs(observation.traffic_fraction - self.traffic_fraction) > 1e-12:
            raise ValueError("observation traffic fraction differs from active canary stage")
        # Snapshot caller-owned mappings and validate every metric before any
        # dedupe token, cost, counter, or per-metric e-process is changed.
        observation = replace(
            observation, metrics=self._validated_metrics(observation.metrics)
        )

        self._seen_unit_tokens.add(unit_token)
        self._total_observations += 1
        if observation.assigned_to_challenger:
            self._challenger_observations += 1
            if self.plan.cumulative_cost_metric is not None:
                self._cumulative_challenger_cost += float(
                    observation.metrics[self.plan.cumulative_cost_metric]
                )

        final_stage = self.stage_index == len(self.plan.stages) - 1
        for monitor in self._monitors.values():
            monitor.update(
                observation,
                plan=self.plan,
                update_superiority=final_stage,
            )

        rollback_reasons = self._rollback_reasons()
        if rollback_reasons:
            self.status = CanaryStatus.ROLLED_BACK
            return self.snapshot(CanaryDecision.ROLLBACK, tuple(rollback_reasons))

        stage_observations = self._total_observations - self._stage_start_observations
        if stage_observations < self.plan.min_observations_per_stage:
            return self.snapshot(
                CanaryDecision.HOLD,
                ("minimum_stage_observations_not_reached",),
            )

        if final_stage:
            ready, reasons = self._promotion_ready()
            if not ready:
                return self.snapshot(CanaryDecision.HOLD, reasons)
            self.status = CanaryStatus.PROMOTED
            return self.snapshot(CanaryDecision.PROMOTE, ("all_online_gates_passed",))

        safe, reasons = self._safe_to_ramp()
        if not safe:
            return self.snapshot(CanaryDecision.HOLD, reasons)
        self.stage_index += 1
        self._stage_start_observations = self._total_observations
        return self.snapshot(CanaryDecision.ADVANCE, ("stage_safety_established",))

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
            stage_observations=self._total_observations - self._stage_start_observations,
            challenger_observations=self._challenger_observations,
            cumulative_challenger_cost=self._cumulative_challenger_cost,
            metric_evidence=tuple(
                self._monitors[name].evidence()
                for name in sorted(self._monitors)
            ),
            reasons=reasons,
        )


@dataclass(frozen=True, slots=True)
class PromotionAuditEvent:
    sequence: int
    kind: str
    payload: Mapping[str, Any]
    previous_hash: str
    event_hash: str


class OnlinePromotionController:
    """Champion-challenger controller with verified routing and hashed audit state."""

    def __init__(
        self,
        *,
        champion_name: str,
        candidate: CanaryCandidate,
        plan: CanaryPlan,
    ) -> None:
        if not champion_name.strip():
            raise ValueError("champion_name cannot be empty")
        if candidate.name != plan.candidate_name:
            raise ValueError("candidate name does not match canary plan")
        if candidate.contract_fingerprint != plan.candidate_contract_fingerprint:
            raise ValueError("candidate contract fingerprint does not match canary plan")
        if candidate.promotion_artifact_fingerprint != plan.source_artifact_fingerprint:
            raise ValueError("candidate promotion artifact does not match canary plan")
        self.champion_name = champion_name
        self.candidate = candidate
        self.plan = plan
        self.router = CanaryRouter(plan)
        self.monitor = OnlineCanaryMonitor(plan)
        self._events: list[PromotionAuditEvent] = []
        self._append(
            "challenger_registered",
            {
                "champion": champion_name,
                "challenger": candidate.name,
                "provider": candidate.provider,
                "model": candidate.model,
                "candidate_contract_fingerprint": candidate.contract_fingerprint,
                "source_commit_sha": candidate.source_commit_sha,
                "source_test_fingerprint": candidate.source_test_fingerprint,
                "source_evidence_manifest_fingerprint": (
                    candidate.source_evidence_manifest_fingerprint
                ),
                "promotion_artifact_fingerprint": candidate.promotion_artifact_fingerprint,
                "canary_plan_fingerprint": plan.fingerprint,
            },
        )

    @staticmethod
    def _snapshot_payload(snapshot: CanarySnapshot) -> dict[str, Any]:
        return {
            "status": snapshot.status.value,
            "decision": snapshot.decision.value,
            "stage_index": snapshot.stage_index,
            "traffic_fraction": snapshot.traffic_fraction,
            "total_observations": snapshot.total_observations,
            "stage_observations": snapshot.stage_observations,
            "challenger_observations": snapshot.challenger_observations,
            "cumulative_challenger_cost": snapshot.cumulative_challenger_cost,
            "reasons": list(snapshot.reasons),
            "metric_evidence": [asdict(item) for item in snapshot.metric_evidence],
        }

    @staticmethod
    def _digest(
        sequence: int,
        kind: str,
        payload: Mapping[str, Any],
        previous_hash: str,
    ) -> str:
        encoded = json.dumps(
            {
                "sequence": sequence,
                "kind": kind,
                "payload": payload,
                "previous_hash": previous_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def _append(self, kind: str, payload: Mapping[str, Any]) -> PromotionAuditEvent:
        sequence = len(self._events)
        previous_hash = self._events[-1].event_hash if self._events else "0" * 64
        primitive = json.loads(json.dumps(payload, sort_keys=True))
        event_hash = self._digest(sequence, kind, primitive, previous_hash)
        event = PromotionAuditEvent(
            sequence=sequence,
            kind=kind,
            payload=primitive,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self._events.append(event)
        return event

    def start(self) -> CanarySnapshot:
        snapshot = self.monitor.start()
        self._append("canary_started", self._snapshot_payload(snapshot))
        return snapshot

    def route(self, analysis_unit_id: str) -> CanaryRoute:
        if self.monitor.status is not CanaryStatus.RUNNING:
            raise RuntimeError("routing requires a running canary")
        return self.router.route(
            analysis_unit_id,
            stage_index=self.monitor.stage_index,
        )

    def observe(self, observation: CanaryObservation) -> CanarySnapshot:
        if self.monitor.status is not CanaryStatus.RUNNING:
            raise RuntimeError("canary observations require RUNNING status")
        expected_route = self.router.route(
            observation.analysis_unit_id,
            stage_index=self.monitor.stage_index,
        )
        if not expected_route.in_canary:
            raise ValueError("analysis unit was not admitted by the active canary stage")
        if observation.assigned_to_challenger != expected_route.assigned_to_challenger:
            raise ValueError("observed arm does not match the pre-registered stable router")
        if abs(observation.traffic_fraction - expected_route.traffic_fraction) > 1e-12:
            raise ValueError("observation traffic fraction differs from stable router")
        if (
            abs(observation.assignment_probability - expected_route.challenger_probability)
            > 1e-12
        ):
            raise ValueError("observation propensity differs from stable router")

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
            self._append(kind, self._snapshot_payload(snapshot))
        if snapshot.decision is CanaryDecision.PROMOTE:
            self.champion_name = self.candidate.name
        return snapshot

    def events(self) -> tuple[PromotionAuditEvent, ...]:
        return tuple(self._events)

    def verify_audit_chain(self) -> bool:
        previous_hash = "0" * 64
        for expected_sequence, event in enumerate(self._events):
            if event.sequence != expected_sequence or event.previous_hash != previous_hash:
                return False
            if (
                self._digest(
                    event.sequence,
                    event.kind,
                    event.payload,
                    event.previous_hash,
                )
                != event.event_hash
            ):
                return False
            previous_hash = event.event_hash
        return True
