from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ._serialization import fingerprint_json
from .causal_evidence import (
    CausalEvidenceBundle,
    CausalOptionEvidenceProducer,
    EvidenceCaseSpec,
)
from .llm_evaluation import (
    LLMBenchmarkCase,
    LLMDecision,
    LLMExperimentPlan,
    LLMHoldoutResult,
    LLMPolicyCandidate,
    LockedLLMBenchmarkArtifact,
    LockedLLMPolicyProtocol,
    SemanticPlanner,
    collect_planner_decisions,
)


@dataclass(frozen=True, slots=True)
class ShadowPlannerEntry:
    candidate: LLMPolicyCandidate
    planner: SemanticPlanner


@dataclass(frozen=True, slots=True)
class LockedShadowBenchmarkRun:
    """Complete validation-selection + one-shot holdout shadow benchmark result."""

    artifact: LockedLLMBenchmarkArtifact
    holdout: LLMHoldoutResult
    selected_candidate: LLMPolicyCandidate
    validation_decisions: tuple[LLMDecision, ...]
    holdout_decisions: tuple[LLMDecision, ...]
    validation_evidence_fingerprint: str
    holdout_evidence_fingerprint: str
    evidence_manifest_fingerprint: str


def _entry_map(
    plan: LLMExperimentPlan,
    entries: Sequence[ShadowPlannerEntry],
) -> dict[str, ShadowPlannerEntry]:
    if not entries:
        raise ValueError("at least one shadow planner entry is required")
    by_name: dict[str, ShadowPlannerEntry] = {}
    for entry in entries:
        name = entry.candidate.name
        if name in by_name:
            raise ValueError(f"duplicate shadow planner candidate: {name}")
        by_name[name] = entry

    declared = {candidate.name: candidate for candidate in plan.candidates}
    if set(by_name) != set(declared):
        missing = sorted(set(declared).difference(by_name))
        unexpected = sorted(set(by_name).difference(declared))
        raise ValueError(
            f"shadow planner registry does not match experiment plan; missing={missing}, unexpected={unexpected}"
        )
    for name, planned in declared.items():
        if by_name[name].candidate != planned:
            raise ValueError(f"shadow planner candidate metadata differs from plan for {name!r}")
    return by_name


def _build_cases(
    specs: Sequence[EvidenceCaseSpec],
    producer: CausalOptionEvidenceProducer,
    *,
    require_promotion_evidence: bool,
) -> tuple[tuple[LLMBenchmarkCase, ...], tuple[CausalEvidenceBundle, ...]]:
    if not specs:
        raise ValueError("at least one evidence case spec is required")
    case_ids = [spec.case_id for spec in specs]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("evidence case ids must be unique within a split")

    cases: list[LLMBenchmarkCase] = []
    bundles: list[CausalEvidenceBundle] = []
    for spec in sorted(specs, key=lambda item: item.case_id):
        bundle = producer.produce(spec)
        if bundle.producer_name != producer.name or bundle.producer_version != producer.version:
            raise ValueError("evidence bundle producer identity does not match active producer")
        cases.append(
            bundle.to_benchmark_case(
                spec,
                require_promotion_evidence=require_promotion_evidence,
            )
        )
        bundles.append(bundle)
    return tuple(cases), tuple(bundles)


def _evidence_fingerprint(
    *,
    split: str,
    producer: CausalOptionEvidenceProducer,
    bundles: Sequence[CausalEvidenceBundle],
    require_promotion_evidence: bool,
) -> str:
    return fingerprint_json(
        {
            "schema": "growthevo.llm-evidence-manifest.v1",
            "split": split,
            "producer": {"name": producer.name, "version": producer.version},
            "require_promotion_evidence": require_promotion_evidence,
            "bundles": [
                {
                    "case_id": bundle.case_id,
                    "bundle_fingerprint": bundle.fingerprint,
                    "estimand": bundle.estimand,
                }
                for bundle in sorted(bundles, key=lambda item: item.case_id)
            ],
        }
    )


def run_locked_shadow_benchmark(
    *,
    plan: LLMExperimentPlan,
    entries: Sequence[ShadowPlannerEntry],
    producer: CausalOptionEvidenceProducer,
    validation_specs: Sequence[EvidenceCaseSpec],
    holdout_specs: Sequence[EvidenceCaseSpec],
    commit_sha: str,
    require_promotion_evidence: bool = True,
) -> LockedShadowBenchmarkRun:
    """Run a locked semantic-policy tournament without exposing causal labels.

    Every declared candidate is evaluated on validation. Only the frozen winner
    is invoked on holdout, so the final causal split is never used to compare all
    model+harness variants. Evidence is constructed evaluator-side and
    ``collect_planner_decisions`` passes only ``belief`` and ``goal`` to planners.
    """

    if not commit_sha.strip():
        raise ValueError("commit_sha cannot be empty")
    registry = _entry_map(plan, entries)

    validation_cases, validation_bundles = _build_cases(
        validation_specs,
        producer,
        require_promotion_evidence=require_promotion_evidence,
    )
    holdout_cases, holdout_bundles = _build_cases(
        holdout_specs,
        producer,
        require_promotion_evidence=require_promotion_evidence,
    )

    validation_ids = {case.case_id for case in validation_cases}
    holdout_ids = {case.case_id for case in holdout_cases}
    overlap = validation_ids.intersection(holdout_ids)
    if overlap:
        raise ValueError(f"validation and holdout case ids overlap: {sorted(overlap)[:3]}")

    validation_decisions: list[LLMDecision] = []
    for candidate in plan.candidates:
        entry = registry[candidate.name]
        validation_decisions.extend(
            collect_planner_decisions(
                candidate_name=candidate.name,
                planner=entry.planner,
                cases=validation_cases,
                trials_per_case=plan.trials_per_case,
            )
        )

    protocol = LockedLLMPolicyProtocol(plan)
    winner = protocol.tune(validation_cases, tuple(validation_decisions))

    winner_entry = registry[winner.name]
    holdout_decisions = collect_planner_decisions(
        candidate_name=winner.name,
        planner=winner_entry.planner,
        cases=holdout_cases,
        trials_per_case=plan.trials_per_case,
    )
    holdout = protocol.evaluate_once(holdout_cases, holdout_decisions)
    artifact = protocol.artifact(holdout, commit_sha=commit_sha)

    validation_evidence_fingerprint = _evidence_fingerprint(
        split="validation",
        producer=producer,
        bundles=validation_bundles,
        require_promotion_evidence=require_promotion_evidence,
    )
    holdout_evidence_fingerprint = _evidence_fingerprint(
        split="holdout",
        producer=producer,
        bundles=holdout_bundles,
        require_promotion_evidence=require_promotion_evidence,
    )
    evidence_manifest_fingerprint = fingerprint_json(
        {
            "schema": "growthevo.llm-evidence-pair.v1",
            "validation": validation_evidence_fingerprint,
            "holdout": holdout_evidence_fingerprint,
            "plan": plan.fingerprint,
            "selected_candidate": winner.name,
            "commit_sha": commit_sha,
        }
    )

    return LockedShadowBenchmarkRun(
        artifact=artifact,
        holdout=holdout,
        selected_candidate=winner,
        validation_decisions=tuple(validation_decisions),
        holdout_decisions=holdout_decisions,
        validation_evidence_fingerprint=validation_evidence_fingerprint,
        holdout_evidence_fingerprint=holdout_evidence_fingerprint,
        evidence_manifest_fingerprint=evidence_manifest_fingerprint,
    )
