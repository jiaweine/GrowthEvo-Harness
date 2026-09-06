from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b, sha256
import json
from math import isfinite, sqrt
from random import Random
from statistics import NormalDist
from typing import Mapping

from .online_promotion import CanaryMetricSpec, HoeffdingMixtureEProcess
from .sequential_causal import (
    FrozenCUPEDSpec,
    GroupSequentialPrimaryMonitor,
    HighPowerCanaryObservation,
    HighPowerCanaryPlan,
)


@dataclass(frozen=True, slots=True)
class BernoulliSequentialScenario:
    """Reproducible randomized DGP for protocol operating-characteristic checks.

    Effects are expressed on the *oriented* metric scale used by GrowthEvo:
    positive means challenger better and negative means challenger worse.  The
    first evidence-lab DGP is intentionally simple and auditable.  More complex
    cluster, survival and censoring DGPs should use new typed scenario identities
    rather than silently changing this contract.
    """

    name: str
    control_rate: float
    benefit_effect: float
    harm_effect: float
    max_observations: int
    covariate_outcome_strength: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("scenario name cannot be empty")
        for field_name, value in (
            ("control_rate", self.control_rate),
            ("benefit_effect", self.benefit_effect),
            ("harm_effect", self.harm_effect),
            ("covariate_outcome_strength", self.covariate_outcome_strength),
        ):
            if not isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if not 0 < self.control_rate < 1:
            raise ValueError("control_rate must lie in (0, 1)")
        if self.benefit_effect <= 0:
            raise ValueError("benefit_effect must be positive on the oriented scale")
        if self.harm_effect >= 0:
            raise ValueError("harm_effect must be negative on the oriented scale")
        if self.max_observations <= 0:
            raise ValueError("max_observations must be positive")
        if abs(self.covariate_outcome_strength) > 0.45:
            raise ValueError("covariate_outcome_strength magnitude must be <= 0.45")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {"schema": "growthevo.bernoulli-sequential-scenario.v1", **asdict(self)}
        )


@dataclass(frozen=True, slots=True)
class MonteCarloAcceptanceGate:
    """Pre-registered acceptance criteria for simulated operating characteristics."""

    max_type_i_upper: float = 0.075
    min_power_lower: float = 0.70
    min_harm_detection_lower: float = 0.70
    max_mean_rollback_delay_fraction: float = 0.80
    confidence_level: float = 0.95
    minimum_replications: int = 1000

    def __post_init__(self) -> None:
        for field_name, value in (
            ("max_type_i_upper", self.max_type_i_upper),
            ("min_power_lower", self.min_power_lower),
            ("min_harm_detection_lower", self.min_harm_detection_lower),
            ("max_mean_rollback_delay_fraction", self.max_mean_rollback_delay_fraction),
            ("confidence_level", self.confidence_level),
        ):
            if not isfinite(value):
                raise ValueError(f"{field_name} must be finite")
        if not 0 < self.max_type_i_upper < 1:
            raise ValueError("max_type_i_upper must lie in (0, 1)")
        if not 0 <= self.min_power_lower <= 1:
            raise ValueError("min_power_lower must lie in [0, 1]")
        if not 0 <= self.min_harm_detection_lower <= 1:
            raise ValueError("min_harm_detection_lower must lie in [0, 1]")
        if not 0 < self.max_mean_rollback_delay_fraction <= 1:
            raise ValueError("max_mean_rollback_delay_fraction must lie in (0, 1]")
        if not 0 < self.confidence_level < 1:
            raise ValueError("confidence_level must lie in (0, 1)")
        if self.minimum_replications < 1000:
            raise ValueError("minimum_replications must be at least 1000")


@dataclass(frozen=True, slots=True)
class SequentialEvidenceLabPlan:
    high_power_plan: HighPowerCanaryPlan
    scenario: BernoulliSequentialScenario
    replications: int
    base_seed: int
    gate: MonteCarloAcceptanceGate = MonteCarloAcceptanceGate()

    def __post_init__(self) -> None:
        if self.replications <= 0:
            raise ValueError("replications must be positive")
        if self.scenario.max_observations < self.high_power_plan.group_sequential.expected_final_stage_observations:
            raise ValueError(
                "scenario max_observations must cover the planned group-sequential horizon"
            )
        metric = self.primary_metric
        if metric.outcome_min > 0 or metric.outcome_max < 1:
            raise ValueError(
                "Bernoulli evidence-lab scenario requires primary metric bounds to contain [0, 1]"
            )

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
                "schema": "growthevo.sequential-evidence-lab-plan.v1",
                "high_power_plan_fingerprint": self.high_power_plan.fingerprint,
                "scenario": asdict(self.scenario),
                "scenario_fingerprint": self.scenario.fingerprint,
                "replications": self.replications,
                "base_seed": self.base_seed,
                "gate": asdict(self.gate),
            }
        )


@dataclass(frozen=True, slots=True)
class MonteCarloRate:
    successes: int
    trials: int
    estimate: float
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class ProtocolOperatingCharacteristics:
    protocol_name: str
    protocol_fingerprint: str
    type_i_error: MonteCarloRate
    power: MonteCarloRate
    harm_detection: MonteCarloRate | None
    mean_benefit_stopping_observations: float
    mean_benefit_stopping_fraction: float
    mean_rollback_delay_observations: float | None
    mean_rollback_delay_fraction: float | None


@dataclass(frozen=True, slots=True)
class SequentialEvidenceLabArtifact:
    commit_sha: str
    lab_plan_fingerprint: str
    high_power_plan_fingerprint: str
    scenario_fingerprint: str
    replications: int
    group_sequential: ProtocolOperatingCharacteristics
    anytime_eprocess: ProtocolOperatingCharacteristics
    acceptance_passed: bool
    acceptance_reasons: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @property
    def fingerprint(self) -> str:
        return sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SequentialProtocolCertificate:
    """Certificate that a frozen protocol passed its pre-registered lab gate."""

    commit_sha: str
    high_power_plan_fingerprint: str
    lab_plan_fingerprint: str
    lab_artifact_fingerprint: str
    scenario_fingerprint: str

    @classmethod
    def from_artifact(
        cls,
        artifact: SequentialEvidenceLabArtifact,
    ) -> "SequentialProtocolCertificate":
        if not artifact.acceptance_passed:
            raise ValueError("sequential evidence-lab artifact did not pass acceptance")
        return cls(
            commit_sha=artifact.commit_sha,
            high_power_plan_fingerprint=artifact.high_power_plan_fingerprint,
            lab_plan_fingerprint=artifact.lab_plan_fingerprint,
            lab_artifact_fingerprint=artifact.fingerprint,
            scenario_fingerprint=artifact.scenario_fingerprint,
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {"schema": "growthevo.sequential-protocol-certificate.v1", **asdict(self)}
        )


def _fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return blake2b(encoded, digest_size=20).hexdigest()


def _derived_seed(plan: SequentialEvidenceLabPlan, label: str) -> int:
    material = f"{plan.base_seed}|{plan.fingerprint}|{label}".encode("utf-8")
    return int.from_bytes(blake2b(material, digest_size=8).digest(), "big")


def _wilson_interval(successes: int, trials: int, confidence_level: float) -> MonteCarloRate:
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("invalid binomial counts")
    phat = successes / trials
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    z2 = z * z
    denominator = 1.0 + z2 / trials
    center = (phat + z2 / (2.0 * trials)) / denominator
    radius = (
        z
        * sqrt(phat * (1.0 - phat) / trials + z2 / (4.0 * trials * trials))
        / denominator
    )
    return MonteCarloRate(
        successes=successes,
        trials=trials,
        estimate=phat,
        lower=max(0.0, center - radius),
        upper=min(1.0, center + radius),
    )


def _actual_treatment_shift(metric: CanaryMetricSpec, oriented_effect: float) -> float:
    return oriented_effect if metric.higher_is_better else -oriented_effect


def _draw_unit(
    rng: Random,
    *,
    scenario: BernoulliSequentialScenario,
    metric: CanaryMetricSpec,
    cuped: FrozenCUPEDSpec | None,
    assigned_to_challenger: bool,
    oriented_effect: float,
) -> tuple[float, dict[str, float]]:
    covariates: dict[str, float] = {}
    covariate_shift = 0.0
    if cuped is not None:
        value = rng.uniform(cuped.covariate_min, cuped.covariate_max)
        covariates[cuped.covariate_name] = value
        span = cuped.covariate_max - cuped.covariate_min
        covariate_shift = (
            scenario.covariate_outcome_strength * (value - cuped.center) / span
        )
    probability = scenario.control_rate + covariate_shift
    if assigned_to_challenger:
        probability += _actual_treatment_shift(metric, oriented_effect)
    probability = min(1.0, max(0.0, probability))
    return (1.0 if rng.random() < probability else 0.0), covariates


def _group_trial(
    plan: SequentialEvidenceLabPlan,
    *,
    rng: Random,
    oriented_effect: float,
) -> tuple[bool, int]:
    hp = plan.high_power_plan
    base = hp.base_plan
    metric = plan.primary_metric
    monitor = GroupSequentialPrimaryMonitor(hp)
    final_stage = len(base.stages) - 1
    max_n = hp.group_sequential.expected_final_stage_observations

    for index in range(max_n):
        challenger = rng.random() < base.challenger_probability
        outcome, covariates = _draw_unit(
            rng,
            scenario=plan.scenario,
            metric=metric,
            cuped=hp.cuped,
            assigned_to_challenger=challenger,
            oriented_effect=oriented_effect,
        )
        evidence = monitor.observe(
            HighPowerCanaryObservation(
                analysis_unit_id=f"lab-group-{index}",
                routing_stage_index=final_stage,
                assigned_to_challenger=challenger,
                assignment_probability=base.challenger_probability,
                traffic_fraction=base.stages[final_stage],
                metrics={metric.name: outcome},
                covariates=covariates,
            )
        )
        if evidence.success:
            return True, index + 1
    return False, max_n


def _ht_contribution(
    *,
    value: float,
    challenger: bool,
    probability: float,
    metric: CanaryMetricSpec,
) -> tuple[float, float, float]:
    raw = value / probability if challenger else -value / (1.0 - probability)
    candidates = (
        metric.outcome_min / probability,
        metric.outcome_max / probability,
        -metric.outcome_min / (1.0 - probability),
        -metric.outcome_max / (1.0 - probability),
    )
    lower = min(candidates)
    upper = max(candidates)
    if metric.higher_is_better:
        return raw, lower, upper
    return -raw, -upper, -lower


def _eprocess_trial(
    plan: SequentialEvidenceLabPlan,
    *,
    rng: Random,
    oriented_effect: float,
    mode: str,
) -> tuple[bool, int]:
    base = plan.high_power_plan.base_plan
    metric = plan.primary_metric
    process = HoeffdingMixtureEProcess(base.e_bet_grid)
    if mode == "success":
        threshold = 1.0 / base.promotion_alpha
    elif mode == "harm":
        harm_tests = len(base.metrics) + sum(
            int(item.absolute_min is not None) + int(item.absolute_max is not None)
            for item in base.metrics
        )
        threshold = harm_tests / base.rollback_family_alpha
    else:
        raise ValueError("unknown e-process simulation mode")

    for index in range(plan.scenario.max_observations):
        challenger = rng.random() < base.challenger_probability
        outcome, _ = _draw_unit(
            rng,
            scenario=plan.scenario,
            metric=metric,
            cuped=None,
            assigned_to_challenger=challenger,
            oriented_effect=oriented_effect,
        )
        contribution, lower, upper = _ht_contribution(
            value=outcome,
            challenger=challenger,
            probability=base.challenger_probability,
            metric=metric,
        )
        if mode == "success":
            process.update_upper_null(
                contribution,
                null_upper=base.primary_min_improvement,
                lower=lower,
                upper=upper,
            )
        else:
            process.update_lower_null(
                contribution,
                null_lower=-metric.noninferiority_margin,
                lower=lower,
                upper=upper,
            )
        if process.max_e_value >= threshold:
            return True, index + 1
    return False, plan.scenario.max_observations


def _simulate_protocol(
    plan: SequentialEvidenceLabPlan,
    *,
    protocol_name: str,
) -> ProtocolOperatingCharacteristics:
    reps = plan.replications
    scenario = plan.scenario
    confidence = plan.gate.confidence_level

    null_successes = 0
    benefit_successes = 0
    benefit_stops = 0
    harm_successes = 0
    harm_stops = 0

    null_rng = Random(_derived_seed(plan, f"{protocol_name}:null"))
    benefit_rng = Random(_derived_seed(plan, f"{protocol_name}:benefit"))
    harm_rng = Random(_derived_seed(plan, f"{protocol_name}:harm"))

    for _ in range(reps):
        if protocol_name == "group_sequential_primary":
            null_hit, _ = _group_trial(plan, rng=null_rng, oriented_effect=0.0)
            benefit_hit, benefit_stop = _group_trial(
                plan,
                rng=benefit_rng,
                oriented_effect=scenario.benefit_effect,
            )
        elif protocol_name == "anytime_primary_eprocess":
            null_hit, _ = _eprocess_trial(
                plan,
                rng=null_rng,
                oriented_effect=0.0,
                mode="success",
            )
            benefit_hit, benefit_stop = _eprocess_trial(
                plan,
                rng=benefit_rng,
                oriented_effect=scenario.benefit_effect,
                mode="success",
            )
        else:
            raise ValueError("unknown protocol_name")
        null_successes += int(null_hit)
        benefit_successes += int(benefit_hit)
        benefit_stops += benefit_stop

        harm_hit, harm_stop = _eprocess_trial(
            plan,
            rng=harm_rng,
            oriented_effect=scenario.harm_effect,
            mode="harm",
        )
        harm_successes += int(harm_hit)
        harm_stops += harm_stop

    if protocol_name == "group_sequential_primary":
        protocol_fingerprint = _fingerprint(
            {
                "schema": "growthevo.group-sequential-protocol-sim.v1",
                "high_power_plan_fingerprint": plan.high_power_plan.fingerprint,
                "group_sequential": asdict(plan.high_power_plan.group_sequential),
                "cuped_fingerprint": (
                    plan.high_power_plan.cuped.fingerprint
                    if plan.high_power_plan.cuped is not None
                    else None
                ),
            }
        )
        benefit_horizon = plan.high_power_plan.group_sequential.expected_final_stage_observations
    else:
        base = plan.high_power_plan.base_plan
        protocol_fingerprint = _fingerprint(
            {
                "schema": "growthevo.anytime-primary-eprocess-sim.v1",
                "base_plan_fingerprint": base.fingerprint,
                "bets": list(base.e_bet_grid),
                "promotion_alpha": base.promotion_alpha,
                "rollback_family_alpha": base.rollback_family_alpha,
            }
        )
        benefit_horizon = scenario.max_observations

    return ProtocolOperatingCharacteristics(
        protocol_name=protocol_name,
        protocol_fingerprint=protocol_fingerprint,
        type_i_error=_wilson_interval(null_successes, reps, confidence),
        power=_wilson_interval(benefit_successes, reps, confidence),
        harm_detection=_wilson_interval(harm_successes, reps, confidence),
        mean_benefit_stopping_observations=benefit_stops / reps,
        mean_benefit_stopping_fraction=(benefit_stops / reps) / benefit_horizon,
        mean_rollback_delay_observations=harm_stops / reps,
        mean_rollback_delay_fraction=(harm_stops / reps) / scenario.max_observations,
    )


def _acceptance_reasons(
    plan: SequentialEvidenceLabPlan,
    results: tuple[ProtocolOperatingCharacteristics, ...],
) -> tuple[str, ...]:
    gate = plan.gate
    reasons: list[str] = []
    if plan.replications < gate.minimum_replications:
        reasons.append("insufficient_monte_carlo_replications")
    for result in results:
        prefix = result.protocol_name
        if result.type_i_error.upper > gate.max_type_i_upper:
            reasons.append(f"{prefix}:type_i_upper_exceeds_gate")
        if result.power.lower < gate.min_power_lower:
            reasons.append(f"{prefix}:power_lower_below_gate")
        if result.harm_detection is None or result.harm_detection.lower < gate.min_harm_detection_lower:
            reasons.append(f"{prefix}:harm_detection_lower_below_gate")
        if (
            result.mean_rollback_delay_fraction is None
            or result.mean_rollback_delay_fraction
            > gate.max_mean_rollback_delay_fraction
        ):
            reasons.append(f"{prefix}:mean_rollback_delay_exceeds_gate")
    return tuple(reasons)


def run_sequential_evidence_lab(
    plan: SequentialEvidenceLabPlan,
    *,
    commit_sha: str,
) -> SequentialEvidenceLabArtifact:
    """Run deterministic Monte Carlo acceptance checks for frozen protocols.

    The artifact is reproducible for the same plan, seed and implementation.
    Passing it is an engineering governance gate, not a theorem: simulation only
    establishes operating characteristics for the declared DGP and horizon.
    """

    if not commit_sha.strip():
        raise ValueError("commit_sha cannot be empty")
    group = _simulate_protocol(plan, protocol_name="group_sequential_primary")
    anytime = _simulate_protocol(plan, protocol_name="anytime_primary_eprocess")
    reasons = _acceptance_reasons(plan, (group, anytime))
    return SequentialEvidenceLabArtifact(
        commit_sha=commit_sha,
        lab_plan_fingerprint=plan.fingerprint,
        high_power_plan_fingerprint=plan.high_power_plan.fingerprint,
        scenario_fingerprint=plan.scenario.fingerprint,
        replications=plan.replications,
        group_sequential=group,
        anytime_eprocess=anytime,
        acceptance_passed=not reasons,
        acceptance_reasons=reasons,
    )
