from __future__ import annotations

from dataclasses import asdict, dataclass
from json import dumps
from math import isfinite, sqrt
from typing import Any, Iterable, Mapping, Protocol, Sequence

from growthevo.models import CausalBelief, GrowthGoal, GrowthOption, to_primitive

from ._serialization import fingerprint_json


_SCHEMA_VERSION = "growthevo.llm-experiment-plan.v1"
_ARTIFACT_SCHEMA_VERSION = "growthevo.locked-llm-benchmark.v1"
_FALLBACK_REASONS = {
    "proposal_low_confidence",
    "critic_veto",
    "circuit_open",
}


class SemanticPlanner(Protocol):
    def plan(self, belief: CausalBelief, goal: GrowthGoal) -> Any: ...


@dataclass(frozen=True, slots=True)
class LLMPolicyCandidate:
    """One pre-registered model+harness configuration.

    The fingerprint fields are intentionally external to provider model names: a
    prompt, schema, critic or safety-threshold change is a new candidate even if
    it uses the same underlying model snapshot.
    """

    name: str
    provider: str
    model: str
    contract_fingerprint: str
    critic_provider: str | None = None
    critic_model: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("name", self.name),
            ("provider", self.provider),
            ("model", self.model),
            ("contract_fingerprint", self.contract_fingerprint),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} cannot be empty")
        if (self.critic_provider is None) != (self.critic_model is None):
            raise ValueError("critic_provider and critic_model must be supplied together")


@dataclass(frozen=True, slots=True)
class CausalOptionEvidence:
    """Hidden holdout evidence for one semantic option.

    ``value`` and ``standard_error`` can come from randomized experiments, DR/OPE,
    or another pre-registered causal estimator. The LLM never receives these
    fields; they are evaluator-only labels.
    """

    value: float
    standard_error: float = 0.0
    feasible: bool = True
    support_coverage: float = 1.0
    effective_sample_ratio: float = 1.0

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

    def conservative_value(self, z_value: float) -> float:
        return self.value - z_value * self.standard_error


@dataclass(frozen=True, slots=True)
class LLMBenchmarkCase:
    """One semantic planning case with evaluator-only causal labels."""

    case_id: str
    belief: CausalBelief
    goal: GrowthGoal
    baseline_option: GrowthOption
    option_evidence: Mapping[GrowthOption, CausalOptionEvidence]
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id cannot be empty")
        if not isfinite(self.weight) or self.weight <= 0:
            raise ValueError("weight must be positive and finite")
        if self.baseline_option not in self.option_evidence:
            raise ValueError("baseline_option must have causal evidence")
        if not self.option_evidence[self.baseline_option].feasible:
            raise ValueError("baseline_option evidence must be feasible")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "belief": to_primitive(self.belief),
            "goal": to_primitive(self.goal),
            "baseline_option": self.baseline_option.value,
            "option_evidence": {
                option.value: asdict(evidence)
                for option, evidence in sorted(
                    self.option_evidence.items(), key=lambda pair: pair[0].value
                )
            },
            "weight": self.weight,
        }


@dataclass(frozen=True, slots=True)
class LLMDecision:
    """One shadow or active planner decision captured for benchmark replay.

    ``option`` is the semantic option to score. In shadow mode this is the model's
    proposal while ``runtime_option`` remains the deterministic baseline. On
    provider/schema/critic fallback, ``option`` is the actual fallback option.
    """

    candidate_name: str
    case_id: str
    option: GrowthOption | None
    runtime_option: GrowthOption | None
    proposed_option: GrowthOption | None = None
    confidence: float | None = None
    accepted: bool = False
    used_llm: bool = True
    reason: str = "accepted"
    latency_ms: float = 0.0
    trial: int = 0

    def __post_init__(self) -> None:
        if not self.candidate_name:
            raise ValueError("candidate_name cannot be empty")
        if not self.case_id:
            raise ValueError("case_id cannot be empty")
        if self.trial < 0:
            raise ValueError("trial must be non-negative")
        if not isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms must be non-negative and finite")
        if self.confidence is not None:
            if not isfinite(self.confidence) or not 0 <= self.confidence <= 1:
                raise ValueError("confidence must be finite and in [0, 1]")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "candidate_name": self.candidate_name,
            "case_id": self.case_id,
            "option": self.option.value if self.option is not None else None,
            "runtime_option": (
                self.runtime_option.value if self.runtime_option is not None else None
            ),
            "proposed_option": (
                self.proposed_option.value if self.proposed_option is not None else None
            ),
            "confidence": self.confidence,
            "accepted": self.accepted,
            "used_llm": self.used_llm,
            "reason": self.reason,
            "latency_ms": self.latency_ms,
            "trial": self.trial,
        }


@dataclass(frozen=True, slots=True)
class LLMExperimentPlan:
    """Pre-registered selection and evidence gates for LLM policy candidates."""

    benchmark: str
    dataset: str
    dataset_source: str
    candidates: tuple[LLMPolicyCandidate, ...]
    trials_per_case: int = 1
    z_value: float = 1.96
    min_decision_coverage: float = 1.0
    max_invalid_rate: float = 0.0
    max_evidence_violation_rate: float = 0.0
    max_hard_stop_violation_rate: float = 0.0
    max_fallback_rate: float = 0.25
    min_support_coverage: float = 0.95
    min_effective_sample_ratio: float = 0.05
    schema_version: str = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("benchmark", self.benchmark),
            ("dataset", self.dataset),
            ("dataset_source", self.dataset_source),
        ):
            if not value:
                raise ValueError(f"{name} cannot be empty")
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(f"unsupported LLM experiment schema: {self.schema_version}")
        if not self.candidates:
            raise ValueError("at least one LLM candidate is required")
        names = [candidate.name for candidate in self.candidates]
        if len(set(names)) != len(names):
            raise ValueError("LLM candidate names must be unique")
        if self.trials_per_case <= 0:
            raise ValueError("trials_per_case must be positive")
        if not isfinite(self.z_value) or self.z_value < 0:
            raise ValueError("z_value must be finite and non-negative")
        for name, value in (
            ("min_decision_coverage", self.min_decision_coverage),
            ("max_invalid_rate", self.max_invalid_rate),
            ("max_evidence_violation_rate", self.max_evidence_violation_rate),
            ("max_hard_stop_violation_rate", self.max_hard_stop_violation_rate),
            ("max_fallback_rate", self.max_fallback_rate),
            ("min_support_coverage", self.min_support_coverage),
            ("min_effective_sample_ratio", self.min_effective_sample_ratio),
        ):
            if not isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite and in [0, 1]")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "dataset": self.dataset,
            "dataset_source": self.dataset_source,
            "trials_per_case": self.trials_per_case,
            "z_value": self.z_value,
            "min_decision_coverage": self.min_decision_coverage,
            "max_invalid_rate": self.max_invalid_rate,
            "max_evidence_violation_rate": self.max_evidence_violation_rate,
            "max_hard_stop_violation_rate": self.max_hard_stop_violation_rate,
            "max_fallback_rate": self.max_fallback_rate,
            "min_support_coverage": self.min_support_coverage,
            "min_effective_sample_ratio": self.min_effective_sample_ratio,
            "selection_objective": "max_validation_conservative_incremental_lcb",
            "candidates": [
                asdict(candidate)
                for candidate in sorted(self.candidates, key=lambda item: item.name)
            ],
        }

    @property
    def fingerprint(self) -> str:
        return fingerprint_json(self.canonical_payload())


@dataclass(frozen=True, slots=True)
class LLMCandidateScore:
    candidate: LLMPolicyCandidate
    case_count: int
    expected_decisions: int
    observed_decisions: int
    decision_coverage: float
    invalid_rate: float
    evidence_violation_rate: float
    hard_stop_violation_rate: float
    fallback_rate: float
    mean_conservative_value: float
    mean_baseline_conservative_value: float
    mean_incremental_over_baseline: float
    incremental_standard_error: float
    incremental_lcb: float
    mean_regret: float
    optimal_rate: float
    confidence_brier: float | None
    mean_latency_ms: float
    p95_latency_ms: float
    eligible: bool


@dataclass(frozen=True, slots=True)
class LLMHoldoutResult:
    candidate: LLMPolicyCandidate
    score: LLMCandidateScore
    test_fingerprint: str


@dataclass(frozen=True, slots=True)
class LockedLLMBenchmarkArtifact:
    benchmark: str
    dataset: str
    dataset_source: str
    commit_sha: str
    experiment_plan_fingerprint: str
    tuning_fingerprint: str
    test_fingerprint: str
    selected_candidate: str
    promotion_eligible: bool
    metrics: Mapping[str, float | int | str | bool | None]
    schema_version: str = _ARTIFACT_SCHEMA_VERSION

    def to_json(self) -> str:
        return dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def _evidence_eligible(evidence: CausalOptionEvidence, plan: LLMExperimentPlan) -> bool:
    return (
        evidence.feasible
        and evidence.support_coverage >= plan.min_support_coverage
        and evidence.effective_sample_ratio >= plan.min_effective_sample_ratio
    )


def _is_fallback_reason(reason: str) -> bool:
    return (
        reason in _FALLBACK_REASONS
        or reason.startswith("llm_failure:")
        or reason.startswith("evidence_fallback:")
    )


def _weighted_mean(values: Sequence[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / total_weight


def _weighted_standard_error(values: Sequence[tuple[float, float]], mean: float) -> float:
    if len(values) <= 1:
        return 0.0
    total_weight = sum(weight for _, weight in values)
    sum_weight_squared = sum(weight * weight for _, weight in values)
    if total_weight <= 0 or sum_weight_squared <= 0:
        return 0.0
    n_eff = (total_weight * total_weight) / sum_weight_squared
    if n_eff <= 1:
        return 0.0
    variance = sum(weight * (value - mean) ** 2 for value, weight in values) / total_weight
    return sqrt(max(0.0, variance) / n_eff)


def _p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(0.95 * len(ordered) + 0.999999) - 1))
    return ordered[index]


def _fingerprint_run(cases: Sequence[LLMBenchmarkCase], decisions: Sequence[LLMDecision]) -> str:
    return fingerprint_json(
        {
            "schema": "growthevo.llm-benchmark-run.v1",
            "cases": [case.canonical_payload() for case in sorted(cases, key=lambda item: item.case_id)],
            "decisions": [
                decision.canonical_payload()
                for decision in sorted(
                    decisions,
                    key=lambda item: (item.candidate_name, item.case_id, item.trial),
                )
            ],
        }
    )


def evaluate_llm_candidate(
    cases: Sequence[LLMBenchmarkCase],
    decisions: Sequence[LLMDecision],
    candidate: LLMPolicyCandidate,
    plan: LLMExperimentPlan,
) -> LLMCandidateScore:
    if not cases:
        raise ValueError("at least one LLM benchmark case is required")
    case_by_id = {case.case_id: case for case in cases}
    if len(case_by_id) != len(cases):
        raise ValueError("LLM benchmark case ids must be unique")

    keyed: dict[tuple[str, int], LLMDecision] = {}
    for decision in decisions:
        if decision.candidate_name != candidate.name:
            continue
        if decision.case_id not in case_by_id:
            raise ValueError(f"decision references unknown case: {decision.case_id}")
        key = (decision.case_id, decision.trial)
        if key in keyed:
            raise ValueError(f"duplicate decision for case/trial: {key}")
        if decision.trial >= plan.trials_per_case:
            raise ValueError("decision trial exceeds pre-registered trials_per_case")
        keyed[key] = decision

    expected = len(cases) * plan.trials_per_case
    observed = len(keyed)
    invalid = 0
    evidence_violations = 0
    hard_stop_violations = 0
    fallbacks = 0
    optimal = 0
    values: list[tuple[float, float]] = []
    baseline_values: list[tuple[float, float]] = []
    improvements: list[tuple[float, float]] = []
    regrets: list[tuple[float, float]] = []
    brier_terms: list[tuple[float, float]] = []
    latencies: list[float] = []

    for case in cases:
        baseline_evidence = case.option_evidence[case.baseline_option]
        if not _evidence_eligible(baseline_evidence, plan):
            raise ValueError(
                f"baseline evidence for case {case.case_id!r} does not pass support gates"
            )
        baseline_value = baseline_evidence.conservative_value(plan.z_value)
        eligible_values = {
            option: evidence.conservative_value(plan.z_value)
            for option, evidence in case.option_evidence.items()
            if _evidence_eligible(evidence, plan)
        }
        if not eligible_values:
            raise ValueError(f"case {case.case_id!r} has no evidence-eligible option")
        best_value = max(eligible_values.values())

        for trial in range(plan.trials_per_case):
            decision = keyed.get((case.case_id, trial))
            chosen = case.baseline_option
            confidence: float | None = None
            if decision is None or decision.option is None:
                invalid += 1
                fallbacks += 1
            else:
                chosen = decision.option
                confidence = decision.confidence
                latencies.append(decision.latency_ms)
                if _is_fallback_reason(decision.reason):
                    fallbacks += 1

            if case.baseline_option in {GrowthOption.HOLDOUT, GrowthOption.STOP}:
                if chosen is not case.baseline_option:
                    hard_stop_violations += 1

            chosen_evidence = case.option_evidence.get(chosen)
            if chosen_evidence is None or not _evidence_eligible(chosen_evidence, plan):
                evidence_violations += 1
                fallbacks += 1
                chosen = case.baseline_option
                chosen_evidence = baseline_evidence

            value = chosen_evidence.conservative_value(plan.z_value)
            improvement = value - baseline_value
            regret = best_value - value
            is_optimal = regret <= 1e-12
            if is_optimal:
                optimal += 1
            weight = case.weight
            values.append((value, weight))
            baseline_values.append((baseline_value, weight))
            improvements.append((improvement, weight))
            regrets.append((regret, weight))
            if confidence is not None:
                target = 1.0 if is_optimal else 0.0
                brier_terms.append(((confidence - target) ** 2, weight))

    coverage = observed / expected if expected else 0.0
    invalid_rate = invalid / expected if expected else 1.0
    evidence_violation_rate = evidence_violations / expected if expected else 1.0
    hard_stop_violation_rate = hard_stop_violations / expected if expected else 1.0
    fallback_rate = min(1.0, fallbacks / expected) if expected else 1.0
    mean_value = _weighted_mean(values)
    mean_baseline = _weighted_mean(baseline_values)
    mean_improvement = _weighted_mean(improvements)
    improvement_se = _weighted_standard_error(improvements, mean_improvement)
    incremental_lcb = mean_improvement - plan.z_value * improvement_se
    mean_regret = _weighted_mean(regrets)
    optimal_rate = optimal / expected if expected else 0.0
    confidence_brier = _weighted_mean(brier_terms) if brier_terms else None
    mean_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = _p95(latencies)

    eligible = (
        coverage >= plan.min_decision_coverage
        and invalid_rate <= plan.max_invalid_rate
        and evidence_violation_rate <= plan.max_evidence_violation_rate
        and hard_stop_violation_rate <= plan.max_hard_stop_violation_rate
        and fallback_rate <= plan.max_fallback_rate
    )

    return LLMCandidateScore(
        candidate=candidate,
        case_count=len(cases),
        expected_decisions=expected,
        observed_decisions=observed,
        decision_coverage=coverage,
        invalid_rate=invalid_rate,
        evidence_violation_rate=evidence_violation_rate,
        hard_stop_violation_rate=hard_stop_violation_rate,
        fallback_rate=fallback_rate,
        mean_conservative_value=mean_value,
        mean_baseline_conservative_value=mean_baseline,
        mean_incremental_over_baseline=mean_improvement,
        incremental_standard_error=improvement_se,
        incremental_lcb=incremental_lcb,
        mean_regret=mean_regret,
        optimal_rate=optimal_rate,
        confidence_brier=confidence_brier,
        mean_latency_ms=mean_latency,
        p95_latency_ms=p95_latency,
        eligible=eligible,
    )


class LockedLLMPolicyProtocol:
    """Select one LLM configuration on validation, then reveal one holdout score.

    Candidate outputs can be collected in zero-impact shadow mode. Causal option
    labels stay evaluator-side, so a model cannot optimize against hidden holdout
    values. Only the frozen validation winner may be scored on final holdout.
    """

    def __init__(self, plan: LLMExperimentPlan) -> None:
        self.plan = plan
        self.validation_scores: tuple[LLMCandidateScore, ...] = ()
        self.selected_candidate: LLMPolicyCandidate | None = None
        self.tuning_fingerprint: str | None = None
        self._tuning_case_ids: frozenset[str] | None = None
        self._evaluated = False

    def tune(
        self,
        cases: Sequence[LLMBenchmarkCase],
        decisions: Sequence[LLMDecision],
    ) -> LLMPolicyCandidate:
        if self.selected_candidate is not None:
            raise RuntimeError("LLM protocol has already been tuned")
        case_ids = [case.case_id for case in cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("LLM validation case ids must be unique")
        declared = {candidate.name for candidate in self.plan.candidates}
        unexpected = {decision.candidate_name for decision in decisions}.difference(declared)
        if unexpected:
            raise ValueError(f"decision manifest contains undeclared candidates: {sorted(unexpected)}")

        scores = tuple(
            evaluate_llm_candidate(cases, decisions, candidate, self.plan)
            for candidate in self.plan.candidates
        )
        eligible_scores = [score for score in scores if score.eligible]
        if not eligible_scores:
            raise ValueError("no LLM candidate passed the pre-registered evidence gates")
        winner = min(
            eligible_scores,
            key=lambda score: (
                -score.incremental_lcb,
                score.mean_regret,
                -score.optimal_rate,
                score.fallback_rate,
                score.mean_latency_ms,
                score.candidate.name,
            ),
        )
        self.validation_scores = scores
        self.selected_candidate = winner.candidate
        self.tuning_fingerprint = _fingerprint_run(cases, decisions)
        self._tuning_case_ids = frozenset(case_ids)
        return winner.candidate

    def evaluate_once(
        self,
        cases: Sequence[LLMBenchmarkCase],
        decisions: Sequence[LLMDecision],
    ) -> LLMHoldoutResult:
        if self.selected_candidate is None or self._tuning_case_ids is None:
            raise RuntimeError("LLM protocol must be tuned before holdout evaluation")
        if self._evaluated:
            raise RuntimeError("LLM holdout has already been revealed")
        case_ids = [case.case_id for case in cases]
        overlap = self._tuning_case_ids.intersection(case_ids)
        if overlap:
            raise ValueError(f"validation and holdout case ids overlap: {sorted(overlap)[:3]}")
        unexpected = {
            decision.candidate_name
            for decision in decisions
            if decision.candidate_name != self.selected_candidate.name
        }
        if unexpected:
            raise ValueError(
                "holdout manifest may contain only the frozen validation winner"
            )

        score = evaluate_llm_candidate(
            cases,
            decisions,
            self.selected_candidate,
            self.plan,
        )
        test_fingerprint = _fingerprint_run(cases, decisions)
        self._evaluated = True
        return LLMHoldoutResult(
            candidate=self.selected_candidate,
            score=score,
            test_fingerprint=test_fingerprint,
        )

    def artifact(
        self,
        holdout: LLMHoldoutResult,
        *,
        commit_sha: str,
    ) -> LockedLLMBenchmarkArtifact:
        if self.tuning_fingerprint is None or self.selected_candidate is None:
            raise RuntimeError("LLM protocol has not completed validation selection")
        if holdout.candidate != self.selected_candidate:
            raise ValueError("holdout result is not for the frozen selected candidate")
        score = holdout.score
        return LockedLLMBenchmarkArtifact(
            benchmark=self.plan.benchmark,
            dataset=self.plan.dataset,
            dataset_source=self.plan.dataset_source,
            commit_sha=commit_sha,
            experiment_plan_fingerprint=self.plan.fingerprint,
            tuning_fingerprint=self.tuning_fingerprint,
            test_fingerprint=holdout.test_fingerprint,
            selected_candidate=self.selected_candidate.name,
            promotion_eligible=score.eligible and score.incremental_lcb > 0.0,
            metrics={
                "decision_coverage": score.decision_coverage,
                "invalid_rate": score.invalid_rate,
                "evidence_violation_rate": score.evidence_violation_rate,
                "hard_stop_violation_rate": score.hard_stop_violation_rate,
                "fallback_rate": score.fallback_rate,
                "mean_conservative_value": score.mean_conservative_value,
                "mean_baseline_conservative_value": score.mean_baseline_conservative_value,
                "mean_incremental_over_baseline": score.mean_incremental_over_baseline,
                "incremental_standard_error": score.incremental_standard_error,
                "incremental_lcb": score.incremental_lcb,
                "mean_regret": score.mean_regret,
                "optimal_rate": score.optimal_rate,
                "confidence_brier": score.confidence_brier,
                "mean_latency_ms": score.mean_latency_ms,
                "p95_latency_ms": score.p95_latency_ms,
                "case_count": score.case_count,
                "expected_decisions": score.expected_decisions,
                "observed_decisions": score.observed_decisions,
                "provider": score.candidate.provider,
                "model": score.candidate.model,
                "contract_fingerprint": score.candidate.contract_fingerprint,
            },
        )


def collect_planner_decisions(
    *,
    candidate_name: str,
    planner: SemanticPlanner,
    cases: Iterable[LLMBenchmarkCase],
    trials_per_case: int = 1,
) -> tuple[LLMDecision, ...]:
    """Collect benchmark decisions without exposing hidden causal labels to the planner.

    For a ``GuardedLLMGrowthPlanner`` in shadow mode, ``audit_snapshot`` reports
    ``reason=shadow_only`` and a proposed option. That proposal becomes the
    counterfactual benchmark option while runtime behavior remains unchanged.
    """

    if trials_per_case <= 0:
        raise ValueError("trials_per_case must be positive")
    rows: list[LLMDecision] = []
    for case in sorted(cases, key=lambda item: item.case_id):
        for trial in range(trials_per_case):
            hypothesis = planner.plan(case.belief, case.goal)
            runtime_option = GrowthOption(hypothesis.option)
            snapshot_method = getattr(planner, "audit_snapshot", None)
            snapshot = snapshot_method() if callable(snapshot_method) else None
            if not isinstance(snapshot, Mapping):
                rows.append(
                    LLMDecision(
                        candidate_name=candidate_name,
                        case_id=case.case_id,
                        option=runtime_option,
                        runtime_option=runtime_option,
                        proposed_option=None,
                        confidence=None,
                        accepted=True,
                        used_llm=False,
                        reason="non_llm_planner",
                        latency_ms=0.0,
                        trial=trial,
                    )
                )
                continue

            proposed_raw = snapshot.get("proposed_option")
            returned_raw = snapshot.get("returned_option")
            proposed = GrowthOption(str(proposed_raw)) if proposed_raw is not None else None
            returned = (
                GrowthOption(str(returned_raw))
                if returned_raw is not None
                else runtime_option
            )
            reason = str(snapshot.get("reason", "accepted"))
            benchmark_option = proposed if reason == "shadow_only" and proposed is not None else returned
            confidence_raw = snapshot.get("confidence")
            confidence = float(confidence_raw) if confidence_raw is not None else None
            rows.append(
                LLMDecision(
                    candidate_name=candidate_name,
                    case_id=case.case_id,
                    option=benchmark_option,
                    runtime_option=returned,
                    proposed_option=proposed,
                    confidence=confidence,
                    accepted=bool(snapshot.get("accepted", False)),
                    used_llm=bool(snapshot.get("used_llm", False)),
                    reason=reason,
                    latency_ms=float(snapshot.get("latency_ms", 0.0)),
                    trial=trial,
                )
            )
    return tuple(rows)
