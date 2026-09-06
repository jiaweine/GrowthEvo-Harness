from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from typing import Mapping, Protocol

from growthevo.models import CausalBelief, GrowthGoal, GrowthOption, to_primitive
from growthevo.rl.ope import OPEEstimate

from ._serialization import fingerprint_json
from .llm_evaluation import CausalOptionEvidence, LLMBenchmarkCase
from .statistics import TargetingInferenceResult


class EvidenceTier(str, Enum):
    """Evidence strength for semantic-policy promotion.

    Tier A/B can participate in real-world promotion when their support gates pass.
    Tier C/D are intentionally diagnostic-only and are filtered before a locked
    promotion benchmark is constructed.
    """

    RANDOMIZED_EXPERIMENT = "tier_a_randomized_experiment"
    PREREGISTERED_OPE = "tier_b_preregistered_ope"
    MODEL_BASED = "tier_c_model_based"
    PROXY = "tier_d_proxy"

    @property
    def promotion_eligible(self) -> bool:
        return self in {
            EvidenceTier.RANDOMIZED_EXPERIMENT,
            EvidenceTier.PREREGISTERED_OPE,
        }


@dataclass(frozen=True, slots=True)
class EvidenceCaseSpec:
    """Planner-visible benchmark context, excluding evaluator-only causal labels."""

    case_id: str
    belief: CausalBelief
    goal: GrowthGoal
    baseline_option: GrowthOption
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id cannot be empty")
        if not isfinite(self.weight) or self.weight <= 0:
            raise ValueError("weight must be positive and finite")

    @property
    def context_fingerprint(self) -> str:
        return fingerprint_json(
            {
                "schema": "growthevo.evidence-case-context.v1",
                "case_id": self.case_id,
                "belief": to_primitive(self.belief),
                "goal": to_primitive(self.goal),
                "baseline_option": self.baseline_option.value,
                "weight": self.weight,
            }
        )


@dataclass(frozen=True, slots=True)
class CausalOptionEstimate:
    """One typed, auditable causal estimate for a semantic growth option."""

    option: GrowthOption
    value: float
    standard_error: float
    tier: EvidenceTier
    source_id: str
    protocol_fingerprint: str
    support_coverage: float = 1.0
    effective_sample_ratio: float = 1.0
    feasible: bool = True
    sample_size: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("value", self.value),
            ("standard_error", self.standard_error),
            ("support_coverage", self.support_coverage),
            ("effective_sample_ratio", self.effective_sample_ratio),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if self.standard_error < 0:
            raise ValueError("standard_error must be non-negative")
        if not 0 <= self.support_coverage <= 1:
            raise ValueError("support_coverage must be in [0, 1]")
        if not 0 <= self.effective_sample_ratio <= 1:
            raise ValueError("effective_sample_ratio must be in [0, 1]")
        if not self.source_id.strip():
            raise ValueError("source_id cannot be empty")
        if not self.protocol_fingerprint.strip():
            raise ValueError("protocol_fingerprint cannot be empty")
        if self.sample_size is not None and self.sample_size <= 0:
            raise ValueError("sample_size must be positive when provided")

    @property
    def fingerprint(self) -> str:
        return fingerprint_json(
            {
                "schema": "growthevo.causal-option-estimate.v1",
                **asdict(self),
            }
        )

    def as_benchmark_evidence(self) -> CausalOptionEvidence:
        return CausalOptionEvidence(
            value=self.value,
            standard_error=self.standard_error,
            feasible=self.feasible,
            support_coverage=self.support_coverage,
            effective_sample_ratio=self.effective_sample_ratio,
        )


@dataclass(frozen=True, slots=True)
class CausalEvidenceBundle:
    """Evaluator-side option evidence bound to one exact benchmark context."""

    case_id: str
    context_fingerprint: str
    estimand: str
    estimates: tuple[CausalOptionEstimate, ...]
    producer_name: str
    producer_version: str

    def __post_init__(self) -> None:
        for name, value in (
            ("case_id", self.case_id),
            ("context_fingerprint", self.context_fingerprint),
            ("estimand", self.estimand),
            ("producer_name", self.producer_name),
            ("producer_version", self.producer_version),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")
        if not self.estimates:
            raise ValueError("evidence bundle requires at least one estimate")
        options = [estimate.option for estimate in self.estimates]
        if len(set(options)) != len(options):
            raise ValueError("evidence bundle options must be unique")

    @property
    def fingerprint(self) -> str:
        return fingerprint_json(
            {
                "schema": "growthevo.causal-evidence-bundle.v1",
                "case_id": self.case_id,
                "context_fingerprint": self.context_fingerprint,
                "estimand": self.estimand,
                "producer_name": self.producer_name,
                "producer_version": self.producer_version,
                "estimates": [
                    {
                        **asdict(estimate),
                        "fingerprint": estimate.fingerprint,
                    }
                    for estimate in sorted(self.estimates, key=lambda item: item.option.value)
                ],
            }
        )

    def estimate_map(self) -> dict[GrowthOption, CausalOptionEstimate]:
        return {estimate.option: estimate for estimate in self.estimates}

    def to_benchmark_case(
        self,
        spec: EvidenceCaseSpec,
        *,
        require_promotion_evidence: bool = True,
    ) -> LLMBenchmarkCase:
        if self.case_id != spec.case_id:
            raise ValueError("evidence bundle case_id does not match case spec")
        if self.context_fingerprint != spec.context_fingerprint:
            raise ValueError("evidence bundle context fingerprint does not match case spec")

        selected = {
            estimate.option: estimate.as_benchmark_evidence()
            for estimate in self.estimates
            if not require_promotion_evidence or estimate.tier.promotion_eligible
        }
        if spec.baseline_option not in selected:
            mode = "promotion-eligible" if require_promotion_evidence else "available"
            raise ValueError(f"baseline option lacks {mode} causal evidence")

        return LLMBenchmarkCase(
            case_id=spec.case_id,
            belief=spec.belief,
            goal=spec.goal,
            baseline_option=spec.baseline_option,
            option_evidence=selected,
            weight=spec.weight,
        )


class CausalOptionEvidenceProducer(Protocol):
    """Provider-neutral source of evaluator-only causal option evidence."""

    name: str
    version: str

    def produce(self, spec: EvidenceCaseSpec) -> CausalEvidenceBundle: ...


class StaticCausalOptionEvidenceProducer:
    """Serve precomputed locked evidence while enforcing exact context binding."""

    def __init__(
        self,
        bundles: Mapping[str, CausalEvidenceBundle],
        *,
        name: str = "static-locked-evidence",
        version: str = "v1",
    ) -> None:
        if not name.strip() or not version.strip():
            raise ValueError("producer name and version cannot be empty")
        if not bundles:
            raise ValueError("at least one evidence bundle is required")
        self.name = name
        self.version = version
        self._bundles = dict(bundles)

    def produce(self, spec: EvidenceCaseSpec) -> CausalEvidenceBundle:
        try:
            bundle = self._bundles[spec.case_id]
        except KeyError as exc:
            raise KeyError(f"no causal evidence registered for case {spec.case_id!r}") from exc
        if bundle.context_fingerprint != spec.context_fingerprint:
            raise ValueError("precomputed evidence does not match current case context")
        return bundle


def fixed_reference_estimate(
    option: GrowthOption,
    *,
    value: float,
    standard_error: float,
    tier: EvidenceTier,
    source_id: str,
    protocol_fingerprint: str,
    support_coverage: float = 1.0,
    effective_sample_ratio: float = 1.0,
    feasible: bool = True,
    sample_size: int | None = None,
) -> CausalOptionEstimate:
    """Create a typed estimate from an already-frozen external causal result."""

    return CausalOptionEstimate(
        option=option,
        value=value,
        standard_error=standard_error,
        tier=tier,
        source_id=source_id,
        protocol_fingerprint=protocol_fingerprint,
        support_coverage=support_coverage,
        effective_sample_ratio=effective_sample_ratio,
        feasible=feasible,
        sample_size=sample_size,
    )


def randomized_targeting_estimate(
    option: GrowthOption,
    result: TargetingInferenceResult,
    *,
    source_id: str,
    protocol_fingerprint: str,
    support_coverage: float,
    effective_sample_ratio: float,
    feasible: bool = True,
) -> CausalOptionEstimate:
    """Adapt a frozen randomized-targeting contrast into Tier-A evidence.

    ``result.point.incremental_value_vs_none`` is an incremental contrast against
    treat-none. All options in the same bundle must use the same estimand.
    Support diagnostics are explicit inputs because a point estimate alone does
    not encode the policy-support contract used to produce it.
    """

    return CausalOptionEstimate(
        option=option,
        value=result.point.incremental_value_vs_none,
        standard_error=result.standard_error,
        tier=EvidenceTier.RANDOMIZED_EXPERIMENT,
        source_id=source_id,
        protocol_fingerprint=protocol_fingerprint,
        support_coverage=support_coverage,
        effective_sample_ratio=effective_sample_ratio,
        feasible=feasible,
        sample_size=result.point.sample_size,
    )


_OPE_FIELDS: dict[str, tuple[str, str]] = {
    "direct_method": ("direct_method", "dm_standard_error"),
    "ips": ("ips", "ips_standard_error"),
    "self_normalized_ips": ("self_normalized_ips", "snips_standard_error"),
    "doubly_robust": ("doubly_robust", "dr_standard_error"),
    "switch_dr": ("switch_dr", "switch_dr_standard_error"),
    "dr_os": ("dr_os", "dr_os_standard_error"),
    "beta_ips": ("beta_ips", "beta_ips_standard_error"),
    "meta_blue": ("meta_blue", "meta_blue_standard_error"),
}


def preregistered_ope_estimate(
    option: GrowthOption,
    estimate: OPEEstimate,
    *,
    estimator: str,
    source_id: str,
    protocol_fingerprint: str,
    feasible: bool = True,
) -> CausalOptionEstimate:
    """Adapt one frozen OPE estimator into Tier-B option evidence."""

    try:
        value_field, se_field = _OPE_FIELDS[estimator]
    except KeyError as exc:
        raise ValueError(f"unsupported OPE estimator for causal evidence: {estimator}") from exc
    return CausalOptionEstimate(
        option=option,
        value=float(getattr(estimate, value_field)),
        standard_error=float(getattr(estimate, se_field)),
        tier=EvidenceTier.PREREGISTERED_OPE,
        source_id=source_id,
        protocol_fingerprint=protocol_fingerprint,
        support_coverage=float(estimate.support_coverage),
        effective_sample_ratio=float(estimate.effective_sample_ratio),
        feasible=feasible,
        sample_size=int(estimate.sample_size),
    )
