from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b
from json import dumps
from math import isfinite
from typing import Iterable, Sequence

from growthevo.rl.ope import LoggedBanditRecord, OPEEstimate, evaluate_policy

from .locked_evaluation import (
    LockedBenchmarkArtifact,
    LockedOPEProtocol,
    OPECandidate,
    OPEHoldoutResult,
    OPEValidationScore,
)


@dataclass(frozen=True, slots=True)
class OPEEvidenceGate:
    """Pre-declared cohort-level evidence requirements for locked OPE.

    Support coverage and ESS are properties of the logged evidence / target-policy
    mismatch, not of a particular estimator. They therefore gate the cohort
    before estimator error is compared. ``require_positive_importance_mass`` is
    intentionally true by default: a model-only value cannot qualify as OPE
    evidence when the target policy has zero logged importance mass.
    """

    min_support_coverage: float = 0.0
    min_effective_sample_ratio: float = 0.0
    require_positive_importance_mass: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_support_coverage <= 1.0:
            raise ValueError("min_support_coverage must be in [0, 1]")
        if not 0.0 <= self.min_effective_sample_ratio <= 1.0:
            raise ValueError("min_effective_sample_ratio must be in [0, 1]")

    def failures(self, estimate: OPEEstimate) -> tuple[str, ...]:
        reasons: list[str] = []
        if not isfinite(estimate.support_coverage):
            reasons.append("support_coverage_non_finite")
        elif estimate.support_coverage < self.min_support_coverage:
            reasons.append(
                "support_coverage_below_minimum:"
                f"{estimate.support_coverage:.12g}<{self.min_support_coverage:.12g}"
            )

        if not isfinite(estimate.effective_sample_ratio):
            reasons.append("effective_sample_ratio_non_finite")
        elif estimate.effective_sample_ratio < self.min_effective_sample_ratio:
            reasons.append(
                "effective_sample_ratio_below_minimum:"
                f"{estimate.effective_sample_ratio:.12g}<"
                f"{self.min_effective_sample_ratio:.12g}"
            )

        if self.require_positive_importance_mass:
            if (
                not isfinite(estimate.mean_importance_weight)
                or estimate.mean_importance_weight <= 0.0
                or not isfinite(estimate.effective_sample_size)
                or estimate.effective_sample_size <= 0.0
                or estimate.support_coverage <= 0.0
            ):
                reasons.append("no_positive_supported_importance_mass")
        return tuple(reasons)


def _protocol_fingerprint(inner_fingerprint: str, gate: OPEEvidenceGate) -> str:
    payload = dumps(
        {
            "schema": "growthevo.ope-evidence-gate.v1",
            "inner_protocol_fingerprint": inner_fingerprint,
            "gate": asdict(gate),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return blake2b(payload, digest_size=20).hexdigest()


class EvidenceGatedOPEProtocol:
    """Locked validation selection with cohort evidence gates before error ranking.

    The wrapper deliberately keeps the underlying ``LockedOPEProtocol`` intact.
    Validation evidence must first satisfy the pre-declared support/ESS contract.
    The final holdout is likewise gated, but once its rows are read the wrapper
    marks that holdout as revealed even if the gate fails. This prevents swapping
    in a different test cohort after seeing that the first one had weak evidence.
    """

    def __init__(
        self,
        candidates: Sequence[OPECandidate],
        *,
        support_propensity_floor: float = 1e-3,
        evidence_gate: OPEEvidenceGate | None = None,
    ) -> None:
        self.evidence_gate = evidence_gate or OPEEvidenceGate()
        self._inner = LockedOPEProtocol(
            candidates,
            support_propensity_floor=support_propensity_floor,
        )
        self.protocol_fingerprint = _protocol_fingerprint(
            self._inner.protocol_fingerprint,
            self.evidence_gate,
        )
        self.validation_diagnostics: OPEEstimate | None = None
        self.holdout_diagnostics: OPEEstimate | None = None
        self.validation_gate_failures: tuple[str, ...] = ()
        self.holdout_gate_failures: tuple[str, ...] = ()
        self._holdout_revealed = False

    @property
    def candidates(self) -> tuple[OPECandidate, ...]:
        return self._inner.candidates

    @property
    def validation_scores(self) -> tuple[OPEValidationScore, ...]:
        return self._inner.validation_scores

    @property
    def selected_candidate(self) -> OPECandidate | None:
        return self._inner.selected_candidate

    @property
    def tuning_fingerprint(self) -> str | None:
        return self._inner.tuning_fingerprint

    @property
    def support_propensity_floor(self) -> float:
        return self._inner.support_propensity_floor

    def _diagnose(self, rows: Sequence[LoggedBanditRecord]) -> OPEEstimate:
        return evaluate_policy(
            rows,
            support_propensity_floor=self.support_propensity_floor,
        )

    def tune(
        self,
        records: Iterable[LoggedBanditRecord],
        *,
        reference_value: float,
    ) -> OPECandidate:
        rows = tuple(records)
        if not rows:
            raise ValueError("at least one OPE record is required")
        diagnostics = self._diagnose(rows)
        failures = self.evidence_gate.failures(diagnostics)
        self.validation_diagnostics = diagnostics
        self.validation_gate_failures = failures
        if failures:
            raise ValueError(
                "validation OPE evidence gate failed: " + "; ".join(failures)
            )
        return self._inner.tune(rows, reference_value=reference_value)

    def evaluate_once(
        self,
        records: Iterable[LoggedBanditRecord],
        *,
        reference_value: float,
    ) -> OPEHoldoutResult:
        if self.selected_candidate is None:
            raise RuntimeError("tune must be completed before test evaluation")
        if self._holdout_revealed:
            raise RuntimeError("test split has already been revealed for this protocol object")
        if not isfinite(reference_value):
            raise ValueError("reference_value must be finite")

        rows = tuple(records)
        if not rows:
            raise ValueError("at least one OPE record is required")

        # The holdout has now been supplied to the evaluation process. Lock it
        # before any diagnostic or inner evaluation can fail.
        self._holdout_revealed = True
        diagnostics = self._diagnose(rows)
        failures = self.evidence_gate.failures(diagnostics)
        self.holdout_diagnostics = diagnostics
        self.holdout_gate_failures = failures
        if failures:
            raise ValueError(
                "holdout OPE evidence gate failed: " + "; ".join(failures)
            )
        return self._inner.evaluate_once(rows, reference_value=reference_value)

    def artifact(
        self,
        holdout: OPEHoldoutResult,
        *,
        benchmark: str,
        dataset: str,
        commit_sha: str,
    ) -> LockedBenchmarkArtifact:
        if self.validation_diagnostics is None or self.holdout_diagnostics is None:
            raise RuntimeError("both validation and holdout evidence must pass before artifact")
        base = self._inner.artifact(
            holdout,
            benchmark=benchmark,
            dataset=dataset,
            commit_sha=commit_sha,
        )
        metrics = dict(base.metrics)
        metrics.update(
            {
                "min_support_coverage": self.evidence_gate.min_support_coverage,
                "min_effective_sample_ratio": self.evidence_gate.min_effective_sample_ratio,
                "require_positive_importance_mass": str(
                    self.evidence_gate.require_positive_importance_mass
                ).lower(),
                "validation_support_coverage": self.validation_diagnostics.support_coverage,
                "validation_effective_sample_ratio": (
                    self.validation_diagnostics.effective_sample_ratio
                ),
            }
        )
        return LockedBenchmarkArtifact(
            benchmark=base.benchmark,
            dataset=base.dataset,
            commit_sha=base.commit_sha,
            protocol_fingerprint=self.protocol_fingerprint,
            tuning_fingerprint=base.tuning_fingerprint,
            test_fingerprint=base.test_fingerprint,
            selected_candidate=base.selected_candidate,
            metrics=metrics,
        )
