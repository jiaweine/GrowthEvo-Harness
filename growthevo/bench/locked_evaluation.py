from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b
from json import dumps
from math import isfinite
from typing import Hashable, Iterable, Literal, Mapping, Sequence

from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel
from growthevo.rl.ope import LoggedBanditRecord, OPEEstimate, evaluate_policy

from .real_world import RandomizedTargetingResult, evaluate_randomized_targeting


OPEEstimatorName = Literal[
    "direct_method",
    "ips",
    "self_normalized_ips",
    "doubly_robust",
    "switch_dr",
    "dr_os",
    "beta_ips",
    "meta_blue",
]


@dataclass(frozen=True, slots=True)
class OPECandidate:
    """One pre-declared OPE configuration eligible for validation selection."""

    name: str
    estimator: OPEEstimatorName
    switch_threshold: float | None = None
    dr_os_lambda: float | None = None
    beta_folds: int = 5

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("candidate name cannot be empty")
        if self.estimator == "switch_dr":
            if (
                self.switch_threshold is None
                or not isfinite(self.switch_threshold)
                or self.switch_threshold <= 0
            ):
                raise ValueError("switch_dr candidate requires a positive finite switch_threshold")
        elif self.switch_threshold is not None:
            raise ValueError("switch_threshold is only valid for switch_dr candidates")
        if self.estimator == "dr_os":
            if (
                self.dr_os_lambda is None
                or not isfinite(self.dr_os_lambda)
                or self.dr_os_lambda <= 0
            ):
                raise ValueError("dr_os candidate requires a positive finite dr_os_lambda")
        elif self.dr_os_lambda is not None:
            raise ValueError("dr_os_lambda is only valid for dr_os candidates")
        if self.beta_folds < 2:
            raise ValueError("beta_folds must be at least 2")


@dataclass(frozen=True, slots=True)
class OPEValidationScore:
    candidate: OPECandidate
    estimate: float
    reference_value: float
    absolute_error: float
    standard_error: float
    effective_sample_ratio: float
    support_coverage: float
    max_importance_weight: float


@dataclass(frozen=True, slots=True)
class OPEHoldoutResult:
    candidate: OPECandidate
    estimate: float
    reference_value: float
    absolute_error: float
    relative_error: float | None
    standard_error: float
    effective_sample_ratio: float
    support_coverage: float
    max_importance_weight: float
    test_fingerprint: str


@dataclass(frozen=True, slots=True)
class TargetingValidationScore:
    candidate_name: str
    result: RandomizedTargetingResult


@dataclass(frozen=True, slots=True)
class TargetingHoldoutResult:
    candidate_name: str
    result: RandomizedTargetingResult
    test_fingerprint: str


@dataclass(frozen=True, slots=True)
class LockedBenchmarkArtifact:
    """Auditable output tying a locked evaluation to code/data/protocol identity."""

    benchmark: str
    dataset: str
    commit_sha: str
    protocol_fingerprint: str
    tuning_fingerprint: str
    test_fingerprint: str
    selected_candidate: str
    metrics: Mapping[str, float | int | str | None]
    schema_version: str = "growthevo.locked-benchmark.v1"

    def __post_init__(self) -> None:
        for name, value in (
            ("benchmark", self.benchmark),
            ("dataset", self.dataset),
            ("commit_sha", self.commit_sha),
            ("protocol_fingerprint", self.protocol_fingerprint),
            ("tuning_fingerprint", self.tuning_fingerprint),
            ("test_fingerprint", self.test_fingerprint),
            ("selected_candidate", self.selected_candidate),
        ):
            if not value:
                raise ValueError(f"{name} cannot be empty")

    def to_json(self) -> str:
        return dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _hash_lines(lines: Iterable[str]) -> str:
    digest = blake2b(digest_size=20)
    for line in sorted(lines):
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _stable_hashable(value: Hashable | None) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return f"bool:{int(value)}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("locked evaluation cluster_id floats must be finite")
        return f"float:{value.hex()}"
    if isinstance(value, str):
        return f"str:{value}"
    if isinstance(value, tuple):
        return "tuple:[" + ",".join(_stable_hashable(item) for item in value) + "]"
    raise ValueError(
        "locked evaluation cluster_id must use stable scalar/tuple identity semantics"
    )


def _ope_record_ids(rows: Sequence[LoggedBanditRecord]) -> tuple[str, ...]:
    if any(row.record_id is None for row in rows):
        raise ValueError("locked evaluation requires record_id for every OPE record")
    record_ids = tuple(str(row.record_id) for row in rows)
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("locked evaluation requires unique OPE record_id values")
    return record_ids


def ope_records_fingerprint(records: Iterable[LoggedBanditRecord]) -> str:
    """Fingerprint OPE rows including target-policy and Q-model evidence."""

    rows = tuple(records)
    if not rows:
        raise ValueError("at least one OPE record is required")
    _ope_record_ids(rows)
    return _hash_lines(
        "|".join(
            (
                str(row.record_id),
                float(row.reward).hex(),
                float(row.behavior_propensity).hex(),
                float(row.target_action_probability).hex(),
                float(row.baseline_q).hex(),
                float(row.target_q).hex(),
                _stable_hashable(row.cluster_id),
            )
        )
        for row in rows
    )


def _treatment_unit_ids(rows: Sequence[LoggedTreatmentRecord]) -> tuple[str, ...]:
    ids = tuple(row.unit_id for row in rows)
    if len(set(ids)) != len(ids):
        raise ValueError("locked evaluation requires unique treatment unit_id values")
    return ids


def treatment_records_fingerprint(records: Iterable[LoggedTreatmentRecord]) -> str:
    """Fingerprint randomized treatment rows independent of source-file order."""

    rows = tuple(records)
    if not rows:
        raise ValueError("at least one treatment record is required")
    _treatment_unit_ids(rows)
    return _hash_lines(
        "|".join(
            (
                row.unit_id,
                row.action.value,
                float(row.outcome).hex(),
                ",".join(float(value).hex() for value in row.features),
                ",".join(
                    f"{action.value}:{float(probability).hex()}"
                    for action, probability in sorted(
                        row.action_propensities.items(), key=lambda item: item[0].value
                    )
                ),
                "none" if row.group_id is None else f"group:{row.group_id}",
            )
        )
        for row in rows
    )


def targeting_evidence_fingerprint(
    records: Iterable[LoggedTreatmentRecord],
    candidate_scores: Mapping[str, Sequence[float]],
) -> str:
    """Fingerprint randomized rows together with candidate model predictions."""

    rows = tuple(records)
    if not rows:
        raise ValueError("at least one treatment record is required")
    unit_ids = _treatment_unit_ids(rows)
    if not candidate_scores:
        raise ValueError("at least one targeting candidate is required")
    lines = [f"data:{treatment_records_fingerprint(rows)}"]
    for candidate_name in sorted(candidate_scores):
        if not candidate_name:
            raise ValueError("targeting candidate names cannot be empty")
        scores = tuple(float(value) for value in candidate_scores[candidate_name])
        if len(scores) != len(rows):
            raise ValueError("candidate scores must align with treatment records")
        if any(not isfinite(score) for score in scores):
            raise ValueError("candidate scores must be finite")
        lines.extend(
            f"score:{candidate_name}|{unit_id}|{score.hex()}"
            for unit_id, score in zip(unit_ids, scores, strict=True)
        )
    return _hash_lines(lines)


def _candidate_protocol_fingerprint(
    candidates: Sequence[OPECandidate],
    support_propensity_floor: float,
) -> str:
    payload = dumps(
        {
            "selection_objective": "validation_absolute_error",
            "support_propensity_floor": support_propensity_floor,
            "candidates": [
                asdict(candidate) for candidate in sorted(candidates, key=lambda item: item.name)
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return _hash_lines((payload,))


def _ope_value_and_se(
    estimate: OPEEstimate,
    estimator: OPEEstimatorName,
) -> tuple[float, float]:
    fields: dict[OPEEstimatorName, tuple[str, str]] = {
        "direct_method": ("direct_method", "dm_standard_error"),
        "ips": ("ips", "ips_standard_error"),
        "self_normalized_ips": ("self_normalized_ips", "snips_standard_error"),
        "doubly_robust": ("doubly_robust", "dr_standard_error"),
        "switch_dr": ("switch_dr", "switch_dr_standard_error"),
        "dr_os": ("dr_os", "dr_os_standard_error"),
        "beta_ips": ("beta_ips", "beta_ips_standard_error"),
        "meta_blue": ("meta_blue", "meta_blue_standard_error"),
    }
    value_name, se_name = fields[estimator]
    return float(getattr(estimate, value_name)), float(getattr(estimate, se_name))


def _evaluate_ope_candidate(
    records: Sequence[LoggedBanditRecord],
    candidate: OPECandidate,
    *,
    support_propensity_floor: float,
) -> tuple[OPEEstimate, float, float]:
    estimate = evaluate_policy(
        records,
        support_propensity_floor=support_propensity_floor,
        switch_threshold=candidate.switch_threshold,
        dr_os_lambda=candidate.dr_os_lambda,
        beta_folds=candidate.beta_folds,
    )
    value, standard_error = _ope_value_and_se(estimate, candidate.estimator)
    return estimate, value, standard_error


def _disjoint_or_raise(tuning_ids: frozenset[str], test_ids: Sequence[str]) -> None:
    overlap = tuning_ids.intersection(test_ids)
    if overlap:
        preview = sorted(overlap)[:3]
        raise ValueError(f"tuning and test identities overlap: {preview}")


class LockedOPEProtocol:
    """Tune estimator/hyperparameters on validation, then reveal one test result.

    The selected configuration is frozen before ``evaluate_once`` sees test data.
    There is deliberately no API to score all candidates on test, and the same
    protocol object refuses a second holdout reveal. Stable record identities are
    also checked for *any* tuning/test overlap, not merely equality of full sets.
    """

    def __init__(
        self,
        candidates: Sequence[OPECandidate],
        *,
        support_propensity_floor: float = 1e-3,
    ) -> None:
        if not candidates:
            raise ValueError("at least one OPE candidate is required")
        if len({candidate.name for candidate in candidates}) != len(candidates):
            raise ValueError("OPE candidate names must be unique")
        if not 0 < support_propensity_floor <= 1:
            raise ValueError("support_propensity_floor must be in (0, 1]")
        self.candidates = tuple(candidates)
        self.support_propensity_floor = float(support_propensity_floor)
        self.protocol_fingerprint = _candidate_protocol_fingerprint(
            self.candidates,
            self.support_propensity_floor,
        )
        self.validation_scores: tuple[OPEValidationScore, ...] = ()
        self.selected_candidate: OPECandidate | None = None
        self.tuning_fingerprint: str | None = None
        self._tuning_ids: frozenset[str] | None = None
        self._evaluated = False

    def tune(
        self,
        records: Iterable[LoggedBanditRecord],
        *,
        reference_value: float,
    ) -> OPECandidate:
        if self.selected_candidate is not None:
            raise RuntimeError("protocol has already been tuned")
        if not isfinite(reference_value):
            raise ValueError("reference_value must be finite")
        rows = tuple(records)
        if not rows:
            raise ValueError("at least one OPE record is required")
        ids = _ope_record_ids(rows)
        self.tuning_fingerprint = ope_records_fingerprint(rows)
        self._tuning_ids = frozenset(ids)
        scores: list[OPEValidationScore] = []
        for candidate in self.candidates:
            estimate, value, standard_error = _evaluate_ope_candidate(
                rows,
                candidate,
                support_propensity_floor=self.support_propensity_floor,
            )
            scores.append(
                OPEValidationScore(
                    candidate=candidate,
                    estimate=value,
                    reference_value=float(reference_value),
                    absolute_error=abs(value - reference_value),
                    standard_error=standard_error,
                    effective_sample_ratio=estimate.effective_sample_ratio,
                    support_coverage=estimate.support_coverage,
                    max_importance_weight=estimate.max_importance_weight,
                )
            )
        self.validation_scores = tuple(scores)
        winner = min(
            scores,
            key=lambda score: (
                score.absolute_error,
                score.standard_error,
                -score.support_coverage,
                -score.effective_sample_ratio,
                score.candidate.name,
            ),
        )
        self.selected_candidate = winner.candidate
        return winner.candidate

    def evaluate_once(
        self,
        records: Iterable[LoggedBanditRecord],
        *,
        reference_value: float,
    ) -> OPEHoldoutResult:
        if (
            self.selected_candidate is None
            or self.tuning_fingerprint is None
            or self._tuning_ids is None
        ):
            raise RuntimeError("tune must be completed before test evaluation")
        if self._evaluated:
            raise RuntimeError("test split has already been revealed for this protocol object")
        if not isfinite(reference_value):
            raise ValueError("reference_value must be finite")
        rows = tuple(records)
        if not rows:
            raise ValueError("at least one OPE record is required")
        test_ids = _ope_record_ids(rows)
        _disjoint_or_raise(self._tuning_ids, test_ids)
        test_fingerprint = ope_records_fingerprint(rows)
        estimate, value, standard_error = _evaluate_ope_candidate(
            rows,
            self.selected_candidate,
            support_propensity_floor=self.support_propensity_floor,
        )
        self._evaluated = True
        relative_error = (
            abs(value - reference_value) / abs(reference_value)
            if abs(reference_value) > 1e-15
            else None
        )
        return OPEHoldoutResult(
            candidate=self.selected_candidate,
            estimate=value,
            reference_value=float(reference_value),
            absolute_error=abs(value - reference_value),
            relative_error=relative_error,
            standard_error=standard_error,
            effective_sample_ratio=estimate.effective_sample_ratio,
            support_coverage=estimate.support_coverage,
            max_importance_weight=estimate.max_importance_weight,
            test_fingerprint=test_fingerprint,
        )

    def artifact(
        self,
        holdout: OPEHoldoutResult,
        *,
        benchmark: str,
        dataset: str,
        commit_sha: str,
    ) -> LockedBenchmarkArtifact:
        if self.selected_candidate is None or self.tuning_fingerprint is None:
            raise RuntimeError("protocol must be tuned before creating an artifact")
        if not self._evaluated:
            raise RuntimeError("test evaluation must complete before creating an artifact")
        if holdout.candidate != self.selected_candidate:
            raise ValueError("holdout result does not match the frozen OPE candidate")
        selected_validation = next(
            score
            for score in self.validation_scores
            if score.candidate == self.selected_candidate
        )
        return LockedBenchmarkArtifact(
            benchmark=benchmark,
            dataset=dataset,
            commit_sha=commit_sha,
            protocol_fingerprint=self.protocol_fingerprint,
            tuning_fingerprint=self.tuning_fingerprint,
            test_fingerprint=holdout.test_fingerprint,
            selected_candidate=self.selected_candidate.name,
            metrics={
                "candidate_count": len(self.candidates),
                "estimator": self.selected_candidate.estimator,
                "validation_absolute_error": selected_validation.absolute_error,
                "estimate": holdout.estimate,
                "reference_value": holdout.reference_value,
                "absolute_error": holdout.absolute_error,
                "relative_error": holdout.relative_error,
                "standard_error": holdout.standard_error,
                "effective_sample_ratio": holdout.effective_sample_ratio,
                "support_coverage": holdout.support_coverage,
                "max_importance_weight": holdout.max_importance_weight,
            },
        )


class LockedTargetingProtocol:
    """Validation-only model selection for randomized targeting benchmarks."""

    def __init__(
        self,
        *,
        selected_fraction: float,
        treatment: Channel = Channel.ADS,
    ) -> None:
        if not 0 < selected_fraction <= 1:
            raise ValueError("selected_fraction must be in (0, 1]")
        if treatment is Channel.NO_TREATMENT:
            raise ValueError("targeting treatment must differ from NO_TREATMENT")
        self.selected_fraction = float(selected_fraction)
        self.treatment = treatment
        self.protocol_fingerprint = _hash_lines(
            (
                dumps(
                    {
                        "selection_objective": "validation_incremental_value_vs_none",
                        "selected_fraction": self.selected_fraction,
                        "treatment": treatment.value,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        )
        self.validation_scores: tuple[TargetingValidationScore, ...] = ()
        self.selected_candidate: str | None = None
        self.tuning_fingerprint: str | None = None
        self._tuning_ids: frozenset[str] | None = None
        self._evaluated = False

    def tune(
        self,
        records: Iterable[LoggedTreatmentRecord],
        candidate_scores: Mapping[str, Sequence[float]],
    ) -> str:
        if self.selected_candidate is not None:
            raise RuntimeError("protocol has already been tuned")
        rows = tuple(records)
        if not rows:
            raise ValueError("at least one treatment record is required")
        ids = _treatment_unit_ids(rows)
        self.tuning_fingerprint = targeting_evidence_fingerprint(rows, candidate_scores)
        self._tuning_ids = frozenset(ids)
        scores: list[TargetingValidationScore] = []
        for name in sorted(candidate_scores):
            result = evaluate_randomized_targeting(
                rows,
                candidate_scores[name],
                selected_fraction=self.selected_fraction,
                treatment=self.treatment,
            )
            scores.append(TargetingValidationScore(candidate_name=name, result=result))
        self.validation_scores = tuple(scores)
        winner = max(
            scores,
            key=lambda score: (
                score.result.incremental_value_vs_none,
                score.result.policy_value,
                score.candidate_name,
            ),
        )
        self.selected_candidate = winner.candidate_name
        return winner.candidate_name

    def evaluate_once(
        self,
        records: Iterable[LoggedTreatmentRecord],
        selected_scores: Sequence[float],
    ) -> TargetingHoldoutResult:
        if (
            self.selected_candidate is None
            or self.tuning_fingerprint is None
            or self._tuning_ids is None
        ):
            raise RuntimeError("tune must be completed before test evaluation")
        if self._evaluated:
            raise RuntimeError("test split has already been revealed for this protocol object")
        rows = tuple(records)
        if not rows:
            raise ValueError("at least one treatment record is required")
        test_ids = _treatment_unit_ids(rows)
        _disjoint_or_raise(self._tuning_ids, test_ids)
        test_fingerprint = targeting_evidence_fingerprint(
            rows,
            {self.selected_candidate: selected_scores},
        )
        result = evaluate_randomized_targeting(
            rows,
            selected_scores,
            selected_fraction=self.selected_fraction,
            treatment=self.treatment,
        )
        self._evaluated = True
        return TargetingHoldoutResult(
            candidate_name=self.selected_candidate,
            result=result,
            test_fingerprint=test_fingerprint,
        )

    def artifact(
        self,
        holdout: TargetingHoldoutResult,
        *,
        benchmark: str,
        dataset: str,
        commit_sha: str,
    ) -> LockedBenchmarkArtifact:
        if self.selected_candidate is None or self.tuning_fingerprint is None:
            raise RuntimeError("protocol must be tuned before creating an artifact")
        if not self._evaluated:
            raise RuntimeError("test evaluation must complete before creating an artifact")
        if holdout.candidate_name != self.selected_candidate:
            raise ValueError("holdout result does not match the frozen targeting candidate")
        selected_validation = next(
            score
            for score in self.validation_scores
            if score.candidate_name == self.selected_candidate
        ).result
        result = holdout.result
        return LockedBenchmarkArtifact(
            benchmark=benchmark,
            dataset=dataset,
            commit_sha=commit_sha,
            protocol_fingerprint=self.protocol_fingerprint,
            tuning_fingerprint=self.tuning_fingerprint,
            test_fingerprint=holdout.test_fingerprint,
            selected_candidate=self.selected_candidate,
            metrics={
                "candidate_count": len(self.validation_scores),
                "validation_incremental_value_vs_none": (
                    selected_validation.incremental_value_vs_none
                ),
                "sample_size": result.sample_size,
                "selected_fraction": result.selected_fraction,
                "policy_value": result.policy_value,
                "treat_none_value": result.treat_none_value,
                "treat_all_value": result.treat_all_value,
                "incremental_value_vs_none": result.incremental_value_vs_none,
            },
        )
