from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import blake2b
from json import dumps, loads
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from .locked_evaluation import OPECandidate
from .ope_evidence_gate import OPEEvidenceGate


_SCHEMA_VERSION = "growthevo.ope-experiment-plan.v1"


@dataclass(frozen=True, slots=True)
class OPEExperimentPlan:
    """Pre-registered upstream + estimator protocol for one locked OPE run.

    The plan freezes choices that are otherwise only implicit in exported JSONL:
    dataset/source identity, policy direction, reward, split protocol, Q backend,
    Monte-Carlo policy replication, evidence gates, and the estimator grid.
    A plan fingerprint can then be bound to the locked protocol fingerprint.
    """

    benchmark: str
    dataset: str
    dataset_source: str
    campaign: str
    behavior_policy: str
    evaluation_policy: str
    reward_definition: str
    split_strategy: str
    validation_fraction: float
    q_model: str
    q_folds: int
    n_sim: int
    random_state: int
    support_propensity_floor: float
    evidence_gate: OPEEvidenceGate
    candidates: tuple[OPECandidate, ...]
    schema_version: str = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("benchmark", self.benchmark),
            ("dataset", self.dataset),
            ("dataset_source", self.dataset_source),
            ("campaign", self.campaign),
            ("behavior_policy", self.behavior_policy),
            ("evaluation_policy", self.evaluation_policy),
            ("reward_definition", self.reward_definition),
            ("split_strategy", self.split_strategy),
            ("q_model", self.q_model),
        ):
            if not value:
                raise ValueError(f"{name} cannot be empty")
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(f"unsupported experiment plan schema: {self.schema_version}")
        if not isfinite(self.validation_fraction) or not 0.0 < self.validation_fraction < 1.0:
            raise ValueError("validation_fraction must be finite and in (0, 1)")
        if self.q_folds < 2:
            raise ValueError("q_folds must be at least 2")
        if self.n_sim <= 0:
            raise ValueError("n_sim must be positive")
        if not 0.0 < self.support_propensity_floor <= 1.0:
            raise ValueError("support_propensity_floor must be in (0, 1]")
        if not self.candidates:
            raise ValueError("experiment plan requires at least one OPE candidate")
        names = [candidate.name for candidate in self.candidates]
        if len(set(names)) != len(names):
            raise ValueError("experiment plan candidate names must be unique")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "dataset": self.dataset,
            "dataset_source": self.dataset_source,
            "campaign": self.campaign,
            "behavior_policy": self.behavior_policy,
            "evaluation_policy": self.evaluation_policy,
            "reward_definition": self.reward_definition,
            "split_strategy": self.split_strategy,
            "validation_fraction": self.validation_fraction,
            "q_model": self.q_model,
            "q_folds": self.q_folds,
            "n_sim": self.n_sim,
            "random_state": self.random_state,
            "support_propensity_floor": self.support_propensity_floor,
            "evidence_gate": asdict(self.evidence_gate),
            "candidates": [
                asdict(candidate)
                for candidate in sorted(self.candidates, key=lambda candidate: candidate.name)
            ],
        }

    @property
    def fingerprint(self) -> str:
        payload = dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return blake2b(payload, digest_size=20).hexdigest()

    def bind_protocol_fingerprint(self, locked_protocol_fingerprint: str) -> str:
        if not locked_protocol_fingerprint:
            raise ValueError("locked_protocol_fingerprint cannot be empty")
        payload = dumps(
            {
                "schema": "growthevo.bound-ope-protocol.v1",
                "experiment_plan_fingerprint": self.fingerprint,
                "locked_protocol_fingerprint": locked_protocol_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return blake2b(payload, digest_size=20).hexdigest()

    def validate_runtime_contract(
        self,
        *,
        benchmark: str,
        dataset: str,
        candidates: Sequence[OPECandidate],
        support_propensity_floor: float,
        evidence_gate: OPEEvidenceGate,
    ) -> None:
        mismatches: list[str] = []
        if benchmark != self.benchmark:
            mismatches.append(f"benchmark:{benchmark!r}!={self.benchmark!r}")
        if dataset != self.dataset:
            mismatches.append(f"dataset:{dataset!r}!={self.dataset!r}")
        if support_propensity_floor != self.support_propensity_floor:
            mismatches.append("support_propensity_floor")
        if evidence_gate != self.evidence_gate:
            mismatches.append("evidence_gate")
        runtime_candidates = tuple(sorted(candidates, key=lambda candidate: candidate.name))
        planned_candidates = tuple(sorted(self.candidates, key=lambda candidate: candidate.name))
        if runtime_candidates != planned_candidates:
            mismatches.append("candidates")
        if mismatches:
            raise ValueError(
                "runtime OPE contract does not match pre-registered plan: "
                + ", ".join(mismatches)
            )

    def validate_export_manifest(self, manifest: Mapping[str, Any]) -> None:
        required_matches: tuple[tuple[str, Any], ...] = (
            ("campaign", self.campaign),
            ("behavior_policy", self.behavior_policy),
            ("evaluation_policy", self.evaluation_policy),
            ("validation_fraction", self.validation_fraction),
            ("q_model", self.q_model),
            ("q_folds", self.q_folds),
            ("n_sim", self.n_sim),
            ("random_state", self.random_state),
        )
        mismatches: list[str] = []
        for key, planned in required_matches:
            if key not in manifest:
                mismatches.append(f"missing:{key}")
                continue
            observed = manifest[key]
            if isinstance(planned, float):
                try:
                    observed_float = float(observed)
                except (TypeError, ValueError):
                    mismatches.append(key)
                    continue
                if observed_float != planned:
                    mismatches.append(key)
            elif observed != planned:
                mismatches.append(key)
        if mismatches:
            raise ValueError(
                "export manifest does not match pre-registered plan: "
                + ", ".join(mismatches)
            )


def _candidate_from_payload(payload: Mapping[str, Any], index: int) -> OPECandidate:
    try:
        return OPECandidate(
            name=str(payload["name"]),
            estimator=payload["estimator"],
            switch_threshold=(
                float(payload["switch_threshold"])
                if payload.get("switch_threshold") is not None
                else None
            ),
            dr_os_lambda=(
                float(payload["dr_os_lambda"])
                if payload.get("dr_os_lambda") is not None
                else None
            ),
            beta_folds=int(payload.get("beta_folds", 5)),
        )
    except KeyError as exc:
        raise ValueError(f"experiment plan candidate {index} is missing {exc.args[0]!r}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid experiment plan candidate {index}: {exc}") from exc


def load_ope_experiment_plan(path: str | Path) -> OPEExperimentPlan:
    resolved = Path(path)
    try:
        payload = loads(resolved.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid experiment plan JSON: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError("experiment plan JSON must be an object")

    required = {
        "schema_version",
        "benchmark",
        "dataset",
        "dataset_source",
        "campaign",
        "behavior_policy",
        "evaluation_policy",
        "reward_definition",
        "split_strategy",
        "validation_fraction",
        "q_model",
        "q_folds",
        "n_sim",
        "random_state",
        "support_propensity_floor",
        "evidence_gate",
        "candidates",
    }
    missing = required.difference(payload)
    unknown = set(payload).difference(required)
    if missing:
        raise ValueError(f"experiment plan is missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"experiment plan has unknown fields: {sorted(unknown)}")

    gate_payload = payload["evidence_gate"]
    if not isinstance(gate_payload, dict):
        raise ValueError("experiment plan evidence_gate must be an object")
    gate_keys = {
        "min_support_coverage",
        "min_effective_sample_ratio",
        "require_positive_importance_mass",
    }
    if set(gate_payload) != gate_keys:
        raise ValueError("experiment plan evidence_gate must use the exact v1 fields")
    evidence_gate = OPEEvidenceGate(
        min_support_coverage=float(gate_payload["min_support_coverage"]),
        min_effective_sample_ratio=float(gate_payload["min_effective_sample_ratio"]),
        require_positive_importance_mass=bool(gate_payload["require_positive_importance_mass"]),
    )

    candidate_payload = payload["candidates"]
    if not isinstance(candidate_payload, list) or not candidate_payload:
        raise ValueError("experiment plan candidates must be a non-empty array")
    candidates: list[OPECandidate] = []
    for index, candidate in enumerate(candidate_payload):
        if not isinstance(candidate, dict):
            raise ValueError(f"experiment plan candidate {index} must be an object")
        candidates.append(_candidate_from_payload(candidate, index))

    return OPEExperimentPlan(
        schema_version=str(payload["schema_version"]),
        benchmark=str(payload["benchmark"]),
        dataset=str(payload["dataset"]),
        dataset_source=str(payload["dataset_source"]),
        campaign=str(payload["campaign"]),
        behavior_policy=str(payload["behavior_policy"]),
        evaluation_policy=str(payload["evaluation_policy"]),
        reward_definition=str(payload["reward_definition"]),
        split_strategy=str(payload["split_strategy"]),
        validation_fraction=float(payload["validation_fraction"]),
        q_model=str(payload["q_model"]),
        q_folds=int(payload["q_folds"]),
        n_sim=int(payload["n_sim"]),
        random_state=int(payload["random_state"]),
        support_propensity_floor=float(payload["support_propensity_floor"]),
        evidence_gate=evidence_gate,
        candidates=tuple(candidates),
    )
