from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b, sha256
import json
from math import erfc, isfinite, log, sqrt
from random import Random
from statistics import NormalDist
from typing import Mapping

from .evidence_lab import MonteCarloRate, SequentialProtocolCertificate
from .online_promotion import CanaryMetricSpec, HoeffdingMixtureEProcess
from .sequential_causal import (
    GroupSequentialPrimaryMonitor,
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
)


@dataclass(frozen=True, slots=True)
class ClusterRepeatedEventStress:
    cluster_size: int = 4
    shared_outcome_probability: float = 0.90

    def __post_init__(self) -> None:
        if self.cluster_size < 2:
            raise ValueError("cluster_size must be at least 2")
        if not 0 <= self.shared_outcome_probability <= 1:
            raise ValueError("shared_outcome_probability must lie in [0, 1]")


@dataclass(frozen=True, slots=True)
class DelayedCensoringStress:
    control_missing_probability: float = 0.05
    challenger_missing_probability: float = 0.35
    challenger_success_extra_missing_probability: float = 0.25

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isfinite(value) or not 0 <= value < 1:
                raise ValueError(f"{name} must lie in [0, 1)")


@dataclass(frozen=True, slots=True)
class SRMStress:
    challenger_logging_probability: float = 0.72
    control_logging_probability: float = 0.98
    p_value_threshold: float = 0.001

    def __post_init__(self) -> None:
        for name in ("challenger_logging_probability", "control_logging_probability"):
            value = getattr(self, name)
            if not isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{name} must lie in (0, 1]")
        if not 0 < self.p_value_threshold < 1:
            raise ValueError("p_value_threshold must lie in (0, 1)")


@dataclass(frozen=True, slots=True)
class HeavyTailStress:
    pareto_shape: float = 1.5
    scale: float = 1.0
    draws_per_replication: int = 128

    def __post_init__(self) -> None:
        if not isfinite(self.pareto_shape) or self.pareto_shape <= 1:
            raise ValueError("pareto_shape must be finite and > 1")
        if not isfinite(self.scale) or self.scale <= 0:
            raise ValueError("scale must be finite and positive")
        if self.draws_per_replication <= 0:
            raise ValueError("draws_per_replication must be positive")


@dataclass(frozen=True, slots=True)
class HeterogeneousEffectStress:
    subgroup_fraction: float = 0.50
    harmed_subgroup_effect: float = -0.30
    benefited_subgroup_effect: float = 0.50

    def __post_init__(self) -> None:
        if not 0 < self.subgroup_fraction < 1:
            raise ValueError("subgroup_fraction must lie in (0, 1)")
        if self.harmed_subgroup_effect >= 0:
            raise ValueError("harmed_subgroup_effect must be negative")
        if self.benefited_subgroup_effect <= 0:
            raise ValueError("benefited_subgroup_effect must be positive")


@dataclass(frozen=True, slots=True)
class NonstationaryEffectStress:
    early_fraction: float = 0.50
    early_effect: float = 0.45
    late_effect: float = -0.45

    def __post_init__(self) -> None:
        if not 0 < self.early_fraction < 1:
            raise ValueError("early_fraction must lie in (0, 1)")
        if self.early_effect <= 0:
            raise ValueError("early_effect must be positive")
        if self.late_effect >= 0:
            raise ValueError("late_effect must be negative")


@dataclass(frozen=True, slots=True)
class SequentialStressSuitePlan:
    high_power_plan: HighPowerCanaryPlan
    replications: int
    base_seed: int
    control_rate: float = 0.50
    cluster: ClusterRepeatedEventStress = ClusterRepeatedEventStress()
    censoring: DelayedCensoringStress = DelayedCensoringStress()
    srm: SRMStress = SRMStress()
    heavy_tail: HeavyTailStress = HeavyTailStress()
    heterogeneity: HeterogeneousEffectStress = HeterogeneousEffectStress()
    nonstationarity: NonstationaryEffectStress = NonstationaryEffectStress()

    def __post_init__(self) -> None:
        if self.replications <= 0:
            raise ValueError("replications must be positive")
        if not 0 < self.control_rate < 1:
            raise ValueError("control_rate must lie in (0, 1)")
        metric = self.primary_metric
        if metric.outcome_min > 0 or metric.outcome_max < 1:
            raise ValueError("binary stress scenarios require primary metric bounds to contain [0, 1]")

    @property
    def primary_metric(self) -> CanaryMetricSpec:
        matches = [
            metric
            for metric in self.high_power_plan.base_plan.metrics
            if metric.name == self.high_power_plan.base_plan.primary_metric
        ]
        if len(matches) != 1:
            raise ValueError("high-power plan primary metric contract is invalid")
        return matches[0]

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "schema": "growthevo.sequential-stress-suite-plan.v1",
                "high_power_plan_fingerprint": self.high_power_plan.fingerprint,
                "replications": self.replications,
                "base_seed": self.base_seed,
                "control_rate": self.control_rate,
                "cluster": asdict(self.cluster),
                "censoring": asdict(self.censoring),
                "srm": asdict(self.srm),
                "heavy_tail": asdict(self.heavy_tail),
                "heterogeneity": asdict(self.heterogeneity),
                "nonstationarity": asdict(self.nonstationarity),
            }
        )


@dataclass(frozen=True, slots=True)
class ClusterStressResult:
    group_false_positive: MonteCarloRate
    anytime_false_positive: MonteCarloRate
    analysis_unit_contract_violated: bool


@dataclass(frozen=True, slots=True)
class CensoringStressResult:
    group_false_positive: MonteCarloRate
    anytime_false_positive: MonteCarloRate
    mean_control_missing_rate: float
    mean_challenger_missing_rate: float
    informative_censoring_present: bool


@dataclass(frozen=True, slots=True)
class SRMStressResult:
    alarm_rate: MonteCarloRate
    mean_challenger_share: float
    expected_challenger_share: float
    integrity_blocker_detected: bool


@dataclass(frozen=True, slots=True)
class HeavyTailStressResult:
    out_of_bound_rate: MonteCarloRate
    rejected_out_of_bound_rate: MonteCarloRate
    fail_closed: bool


@dataclass(frozen=True, slots=True)
class HeterogeneityStressResult:
    group_promotion_rate: MonteCarloRate
    anytime_promotion_rate: MonteCarloRate
    harmed_subgroup_fraction: float
    hidden_subgroup_harm_present: bool


@dataclass(frozen=True, slots=True)
class NonstationaryStressResult:
    group_early_promotion_rate: MonteCarloRate
    anytime_early_promotion_rate: MonteCarloRate
    final_average_effect: float
    sign_reversal_present: bool


@dataclass(frozen=True, slots=True)
class SequentialStressArtifact:
    commit_sha: str
    stress_plan_fingerprint: str
    high_power_plan_fingerprint: str
    cluster: ClusterStressResult
    censoring: CensoringStressResult
    srm: SRMStressResult
    heavy_tail: HeavyTailStressResult
    heterogeneity: HeterogeneityStressResult
    nonstationarity: NonstationaryStressResult
    robust_ready: bool
    blockers: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @property
    def fingerprint(self) -> str:
        return sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RobustSequentialProtocolCertificate:
    """Future admission credential requiring both nominal and stress qualification.

    This certificate is deliberately not consumed by the production controller.
    The current protocol is expected to expose blockers under adversarial DGPs;
    callers cannot manufacture a robust credential from a failing stress artifact.
    """

    nominal_certificate_fingerprint: str
    stress_artifact_fingerprint: str
    high_power_plan_fingerprint: str
    commit_sha: str

    @classmethod
    def issue(
        cls,
        *,
        nominal: SequentialProtocolCertificate,
        stress: SequentialStressArtifact,
    ) -> "RobustSequentialProtocolCertificate":
        if not stress.robust_ready:
            raise ValueError("stress artifact has unresolved robustness blockers")
        if nominal.high_power_plan_fingerprint != stress.high_power_plan_fingerprint:
            raise ValueError("nominal and stress artifacts target different high-power plans")
        if nominal.commit_sha != stress.commit_sha:
            raise ValueError("nominal and stress artifacts target different commits")
        return cls(
            nominal_certificate_fingerprint=nominal.fingerprint,
            stress_artifact_fingerprint=stress.fingerprint,
            high_power_plan_fingerprint=stress.high_power_plan_fingerprint,
            commit_sha=stress.commit_sha,
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {"schema": "growthevo.robust-sequential-protocol-certificate.v1", **asdict(self)}
        )


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return blake2b(encoded, digest_size=20).hexdigest()


def _seed(plan: SequentialStressSuitePlan, label: str) -> int:
    raw = f"{plan.base_seed}|{plan.fingerprint}|{label}".encode("utf-8")
    return int.from_bytes(blake2b(raw, digest_size=8).digest(), "big")


def _wilson(successes: int, trials: int, confidence: float = 0.95) -> MonteCarloRate:
    if trials <= 0:
        raise ValueError("trials must be positive")
    phat = successes / trials
    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    z2 = z * z
    denom = 1.0 + z2 / trials
    center = (phat + z2 / (2.0 * trials)) / denom
    radius = z * sqrt(phat * (1.0 - phat) / trials + z2 / (4.0 * trials * trials)) / denom
    return MonteCarloRate(
        successes=successes,
        trials=trials,
        estimate=phat,
        lower=max(0.0, center - radius),
        upper=min(1.0, center + radius),
    )


def _actual_shift(metric: CanaryMetricSpec, oriented_effect: float) -> float:
    return oriented_effect if metric.higher_is_better else -oriented_effect


def _draw_binary(
    rng: Random,
    *,
    control_rate: float,
    metric: CanaryMetricSpec,
    challenger: bool,
    oriented_effect: float,
) -> float:
    probability = control_rate + (_actual_shift(metric, oriented_effect) if challenger else 0.0)
    probability = min(1.0, max(0.0, probability))
    return 1.0 if rng.random() < probability else 0.0


def _observation(
    plan: SequentialStressSuitePlan,
    *,
    unit_id: str,
    challenger: bool,
    outcome: float,
) -> HighPowerCanaryObservation:
    hp = plan.high_power_plan
    base = hp.base_plan
    final_stage = len(base.stages) - 1
    covariates = (
        {hp.cuped.covariate_name: hp.cuped.center}
        if hp.cuped is not None
        else {}
    )
    return HighPowerCanaryObservation(
        analysis_unit_id=unit_id,
        routing_stage_index=final_stage,
        assigned_to_challenger=challenger,
        assignment_probability=base.challenger_probability,
        traffic_fraction=base.stages[final_stage],
        metrics={plan.primary_metric.name: outcome},
        covariates=covariates,
    )


def _group_hit(plan: SequentialStressSuitePlan, stream: list[tuple[bool, float]]) -> tuple[bool, int]:
    monitor = GroupSequentialPrimaryMonitor(plan.high_power_plan)
    max_n = plan.high_power_plan.group_sequential.expected_final_stage_observations
    for index, (challenger, outcome) in enumerate(stream[:max_n]):
        evidence = monitor.observe(
            _observation(
                plan,
                unit_id=f"stress-group-{index}",
                challenger=challenger,
                outcome=outcome,
            )
        )
        if evidence.success:
            return True, index + 1
    return False, min(len(stream), max_n)


def _ht_contribution(
    metric: CanaryMetricSpec,
    *,
    challenger: bool,
    probability: float,
    value: float,
) -> tuple[float, float, float]:
    raw = value / probability if challenger else -value / (1.0 - probability)
    candidates = (
        metric.outcome_min / probability,
        metric.outcome_max / probability,
        -metric.outcome_min / (1.0 - probability),
        -metric.outcome_max / (1.0 - probability),
    )
    lower, upper = min(candidates), max(candidates)
    return (raw, lower, upper) if metric.higher_is_better else (-raw, -upper, -lower)


def _anytime_hit(plan: SequentialStressSuitePlan, stream: list[tuple[bool, float]]) -> tuple[bool, int]:
    base = plan.high_power_plan.base_plan
    metric = plan.primary_metric
    process = HoeffdingMixtureEProcess(base.e_bet_grid)
    threshold = 1.0 / base.promotion_alpha
    for index, (challenger, outcome) in enumerate(stream):
        value, lower, upper = _ht_contribution(
            metric,
            challenger=challenger,
            probability=base.challenger_probability,
            value=outcome,
        )
        process.update_upper_null(
            value,
            null_upper=base.primary_min_improvement,
            lower=lower,
            upper=upper,
        )
        if process.max_e_value >= threshold:
            return True, index + 1
    return False, len(stream)


def _cluster_stress(plan: SequentialStressSuitePlan) -> ClusterStressResult:
    spec = plan.cluster
    metric = plan.primary_metric
    horizon = plan.high_power_plan.group_sequential.expected_final_stage_observations
    group_hits = 0
    anytime_hits = 0
    rng = Random(_seed(plan, "cluster"))
    for rep in range(plan.replications):
        stream: list[tuple[bool, float]] = []
        cluster_index = 0
        while len(stream) < horizon:
            challenger = rng.random() < plan.high_power_plan.base_plan.challenger_probability
            shared = 1.0 if rng.random() < plan.control_rate else 0.0
            for _ in range(spec.cluster_size):
                if rng.random() < spec.shared_outcome_probability:
                    outcome = shared
                else:
                    outcome = _draw_binary(
                        rng,
                        control_rate=plan.control_rate,
                        metric=metric,
                        challenger=challenger,
                        oriented_effect=0.0,
                    )
                # Deliberately emulate the invalid event-as-analysis-unit pipeline.
                stream.append((challenger, outcome))
                if len(stream) >= horizon:
                    break
            cluster_index += 1
        group_hits += int(_group_hit(plan, stream)[0])
        anytime_hits += int(_anytime_hit(plan, stream)[0])
    return ClusterStressResult(
        group_false_positive=_wilson(group_hits, plan.replications),
        anytime_false_positive=_wilson(anytime_hits, plan.replications),
        analysis_unit_contract_violated=True,
    )


def _censoring_stress(plan: SequentialStressSuitePlan) -> CensoringStressResult:
    spec = plan.censoring
    metric = plan.primary_metric
    horizon = plan.high_power_plan.group_sequential.expected_final_stage_observations
    group_hits = 0
    anytime_hits = 0
    missing_control = 0
    missing_challenger = 0
    assigned_control = 0
    assigned_challenger = 0
    rng = Random(_seed(plan, "censoring"))
    for _ in range(plan.replications):
        stream: list[tuple[bool, float]] = []
        while len(stream) < horizon:
            challenger = rng.random() < plan.high_power_plan.base_plan.challenger_probability
            outcome = _draw_binary(
                rng,
                control_rate=plan.control_rate,
                metric=metric,
                challenger=challenger,
                oriented_effect=0.0,
            )
            if challenger:
                assigned_challenger += 1
                missing_probability = spec.challenger_missing_probability
                if outcome > 0.5:
                    missing_probability = min(
                        0.999,
                        missing_probability + spec.challenger_success_extra_missing_probability,
                    )
                missing = rng.random() < missing_probability
                missing_challenger += int(missing)
            else:
                assigned_control += 1
                missing = rng.random() < spec.control_missing_probability
                missing_control += int(missing)
            if not missing:
                stream.append((challenger, outcome))
        group_hits += int(_group_hit(plan, stream)[0])
        anytime_hits += int(_anytime_hit(plan, stream)[0])
    control_rate = missing_control / assigned_control if assigned_control else 0.0
    challenger_rate = missing_challenger / assigned_challenger if assigned_challenger else 0.0
    return CensoringStressResult(
        group_false_positive=_wilson(group_hits, plan.replications),
        anytime_false_positive=_wilson(anytime_hits, plan.replications),
        mean_control_missing_rate=control_rate,
        mean_challenger_missing_rate=challenger_rate,
        informative_censoring_present=abs(challenger_rate - control_rate) > 0.05,
    )


def _srm_p_value(challenger: int, control: int, expected_challenger_share: float) -> float:
    total = challenger + control
    if total <= 0:
        return 1.0
    expected_c = total * expected_challenger_share
    expected_o = total - expected_c
    if expected_c <= 0 or expected_o <= 0:
        return 0.0
    chi2 = (challenger - expected_c) ** 2 / expected_c + (control - expected_o) ** 2 / expected_o
    return erfc(sqrt(chi2 / 2.0))


def _srm_stress(plan: SequentialStressSuitePlan) -> SRMStressResult:
    spec = plan.srm
    p = plan.high_power_plan.base_plan.challenger_probability
    horizon = plan.high_power_plan.group_sequential.expected_final_stage_observations
    alarms = 0
    challenger_logged_total = 0
    total_logged = 0
    rng = Random(_seed(plan, "srm"))
    for _ in range(plan.replications):
        challenger_logged = 0
        control_logged = 0
        for _ in range(horizon):
            challenger = rng.random() < p
            logging_probability = (
                spec.challenger_logging_probability if challenger else spec.control_logging_probability
            )
            if rng.random() < logging_probability:
                if challenger:
                    challenger_logged += 1
                else:
                    control_logged += 1
        alarms += int(
            _srm_p_value(challenger_logged, control_logged, p) < spec.p_value_threshold
        )
        challenger_logged_total += challenger_logged
        total_logged += challenger_logged + control_logged
    share = challenger_logged_total / total_logged if total_logged else 0.0
    alarm_rate = _wilson(alarms, plan.replications)
    return SRMStressResult(
        alarm_rate=alarm_rate,
        mean_challenger_share=share,
        expected_challenger_share=p,
        integrity_blocker_detected=alarm_rate.estimate > 0.50,
    )


def _pareto(rng: Random, *, shape: float, scale: float) -> float:
    # Inverse CDF for Pareto(scale, shape), with U in (0, 1].
    u = max(1e-15, 1.0 - rng.random())
    return scale / (u ** (1.0 / shape))


def _heavy_tail_stress(plan: SequentialStressSuitePlan) -> HeavyTailStressResult:
    spec = plan.heavy_tail
    metric = plan.primary_metric
    trials = plan.replications * spec.draws_per_replication
    out_of_bound = 0
    rejected = 0
    rng = Random(_seed(plan, "heavy-tail"))
    monitor = GroupSequentialPrimaryMonitor(plan.high_power_plan)
    for index in range(trials):
        value = _pareto(rng, shape=spec.pareto_shape, scale=spec.scale)
        outside = value < metric.outcome_min or value > metric.outcome_max
        out_of_bound += int(outside)
        if not outside:
            continue
        try:
            monitor.validate_observation(
                _observation(
                    plan,
                    unit_id=f"heavy-{index}",
                    challenger=bool(index % 2),
                    outcome=value,
                )
            )
        except ValueError:
            rejected += 1
    out_rate = _wilson(out_of_bound, trials)
    reject_rate = _wilson(rejected, max(1, out_of_bound))
    return HeavyTailStressResult(
        out_of_bound_rate=out_rate,
        rejected_out_of_bound_rate=reject_rate,
        fail_closed=(out_of_bound > 0 and rejected == out_of_bound),
    )


def _heterogeneity_stress(plan: SequentialStressSuitePlan) -> HeterogeneityStressResult:
    spec = plan.heterogeneity
    metric = plan.primary_metric
    horizon = plan.high_power_plan.group_sequential.expected_final_stage_observations
    group_hits = 0
    anytime_hits = 0
    rng = Random(_seed(plan, "heterogeneity"))
    for _ in range(plan.replications):
        stream: list[tuple[bool, float]] = []
        for _ in range(horizon):
            challenger = rng.random() < plan.high_power_plan.base_plan.challenger_probability
            harmed = rng.random() < spec.subgroup_fraction
            effect = spec.harmed_subgroup_effect if harmed else spec.benefited_subgroup_effect
            outcome = _draw_binary(
                rng,
                control_rate=plan.control_rate,
                metric=metric,
                challenger=challenger,
                oriented_effect=effect,
            )
            stream.append((challenger, outcome))
        group_hits += int(_group_hit(plan, stream)[0])
        anytime_hits += int(_anytime_hit(plan, stream)[0])
    return HeterogeneityStressResult(
        group_promotion_rate=_wilson(group_hits, plan.replications),
        anytime_promotion_rate=_wilson(anytime_hits, plan.replications),
        harmed_subgroup_fraction=spec.subgroup_fraction,
        hidden_subgroup_harm_present=True,
    )


def _nonstationary_stress(plan: SequentialStressSuitePlan) -> NonstationaryStressResult:
    spec = plan.nonstationarity
    metric = plan.primary_metric
    horizon = plan.high_power_plan.group_sequential.expected_final_stage_observations
    early_n = max(1, min(horizon - 1, round(horizon * spec.early_fraction)))
    group_hits = 0
    anytime_hits = 0
    rng = Random(_seed(plan, "nonstationarity"))
    for _ in range(plan.replications):
        stream: list[tuple[bool, float]] = []
        for index in range(horizon):
            challenger = rng.random() < plan.high_power_plan.base_plan.challenger_probability
            effect = spec.early_effect if index < early_n else spec.late_effect
            outcome = _draw_binary(
                rng,
                control_rate=plan.control_rate,
                metric=metric,
                challenger=challenger,
                oriented_effect=effect,
            )
            stream.append((challenger, outcome))
        group_hit, group_stop = _group_hit(plan, stream)
        anytime_hit, anytime_stop = _anytime_hit(plan, stream)
        group_hits += int(group_hit and group_stop <= early_n)
        anytime_hits += int(anytime_hit and anytime_stop <= early_n)
    final_average = spec.early_fraction * spec.early_effect + (1.0 - spec.early_fraction) * spec.late_effect
    return NonstationaryStressResult(
        group_early_promotion_rate=_wilson(group_hits, plan.replications),
        anytime_early_promotion_rate=_wilson(anytime_hits, plan.replications),
        final_average_effect=final_average,
        sign_reversal_present=spec.early_effect > 0 > spec.late_effect,
    )


def _blockers(
    *,
    cluster: ClusterStressResult,
    censoring: CensoringStressResult,
    srm: SRMStressResult,
    heavy_tail: HeavyTailStressResult,
    heterogeneity: HeterogeneityStressResult,
    nonstationarity: NonstationaryStressResult,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if cluster.analysis_unit_contract_violated:
        blockers.append("cluster:repeated_events_require_upstream_cluster_aggregation")
    if censoring.informative_censoring_present:
        blockers.append("censoring:arm_or_outcome_dependent_missingness_requires_explicit_estimand")
    if not srm.integrity_blocker_detected:
        blockers.append("srm:assignment_integrity_corruption_not_reliably_detected")
    if not heavy_tail.fail_closed:
        blockers.append("heavy_tail:out_of_bound_outcomes_did_not_fail_closed")
    if heterogeneity.hidden_subgroup_harm_present:
        blockers.append("heterogeneity:aggregate_success_can_mask_harmed_subgroups")
    if nonstationarity.sign_reversal_present and (
        nonstationarity.group_early_promotion_rate.successes > 0
        or nonstationarity.anytime_early_promotion_rate.successes > 0
    ):
        blockers.append("nonstationarity:early_success_can_precede_effect_reversal")
    return tuple(blockers)


def run_sequential_stress_suite(
    plan: SequentialStressSuitePlan,
    *,
    commit_sha: str,
) -> SequentialStressArtifact:
    """Exercise frozen sequential protocols under adversarial data-generating regimes.

    A stress artifact may intentionally fail while the software test suite passes.
    That distinction is the point: CI validates that failure modes are detected
    reproducibly; it does not redefine an adverse DGP until the protocol looks good.
    """

    if not commit_sha.strip():
        raise ValueError("commit_sha cannot be empty")
    cluster = _cluster_stress(plan)
    censoring = _censoring_stress(plan)
    srm = _srm_stress(plan)
    heavy_tail = _heavy_tail_stress(plan)
    heterogeneity = _heterogeneity_stress(plan)
    nonstationarity = _nonstationary_stress(plan)
    blockers = _blockers(
        cluster=cluster,
        censoring=censoring,
        srm=srm,
        heavy_tail=heavy_tail,
        heterogeneity=heterogeneity,
        nonstationarity=nonstationarity,
    )
    return SequentialStressArtifact(
        commit_sha=commit_sha,
        stress_plan_fingerprint=plan.fingerprint,
        high_power_plan_fingerprint=plan.high_power_plan.fingerprint,
        cluster=cluster,
        censoring=censoring,
        srm=srm,
        heavy_tail=heavy_tail,
        heterogeneity=heterogeneity,
        nonstationarity=nonstationarity,
        robust_ready=not blockers,
        blockers=blockers,
    )
