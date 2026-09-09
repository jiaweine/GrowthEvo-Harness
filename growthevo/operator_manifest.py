from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from json import load
from math import isfinite
from pathlib import Path
from typing import Any

from growthevo.bench._serialization import fingerprint_json
from growthevo.bench.llm_candidate_factory import (
    LLMEndpointSpec,
    ShadowCandidateSpec,
    shadow_candidate_metadata,
)
from growthevo.bench.llm_evaluation import LLMExperimentPlan
from growthevo.bench.llm_shadow_runner import ShadowBenchmarkPlan
from growthevo.llm.planner import LLMPlannerConfig


_SCHEMA_VERSION = "growthevo.production-operator-manifest.v1"


def _mapping(value: Any, *, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    return value


def _strict_keys(
    payload: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
    context: str,
) -> None:
    missing = sorted(required.difference(payload))
    unexpected = sorted(set(payload).difference(allowed))
    if missing:
        raise ValueError(f"{context} is missing required keys: {missing}")
    if unexpected:
        raise ValueError(f"{context} contains unexpected keys: {unexpected}")


def _string(value: Any, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def _optional_string(value: Any, *, context: str) -> str | None:
    if value is None:
        return None
    return _string(value, context=context)


def _bool(value: Any, *, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{context} must be a boolean")
    return value


def _int(value: Any, *, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{context} must be an integer")
    return value


def _number(value: Any, *, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a number")
    converted = float(value)
    if not isfinite(converted):
        raise ValueError(f"{context} must be finite")
    return converted


def _endpoint(payload: Any, *, context: str) -> LLMEndpointSpec:
    item = _mapping(payload, context=context)
    _strict_keys(
        item,
        allowed={"provider", "model", "reasoning_effort", "store", "max_tokens"},
        required={"provider", "model"},
        context=context,
    )
    provider = _string(item["provider"], context=f"{context}.provider")
    if provider not in {"openai", "anthropic", "google"}:
        raise ValueError(f"{context}.provider is unsupported: {provider!r}")
    return LLMEndpointSpec(
        provider=provider,  # type: ignore[arg-type]
        model=_string(item["model"], context=f"{context}.model"),
        reasoning_effort=_optional_string(
            item.get("reasoning_effort"),
            context=f"{context}.reasoning_effort",
        ),
        store=_bool(item.get("store", False), context=f"{context}.store"),
        max_tokens=_int(
            item.get("max_tokens", 900),
            context=f"{context}.max_tokens",
        ),
    )


def _planner_config(payload: Any, *, context: str) -> LLMPlannerConfig:
    item = _mapping(payload, context=context)
    allowed = {
        "min_confidence",
        "critic_min_confidence",
        "max_consecutive_failures",
        "circuit_cooldown_seconds",
        "max_rationale_chars",
        "allow_exploration",
        "shadow_mode",
    }
    _strict_keys(item, allowed=allowed, required=set(), context=context)
    return LLMPlannerConfig(
        min_confidence=_number(
            item.get("min_confidence", 0.70),
            context=f"{context}.min_confidence",
        ),
        critic_min_confidence=_number(
            item.get("critic_min_confidence", 0.65),
            context=f"{context}.critic_min_confidence",
        ),
        max_consecutive_failures=_int(
            item.get("max_consecutive_failures", 3),
            context=f"{context}.max_consecutive_failures",
        ),
        circuit_cooldown_seconds=_number(
            item.get("circuit_cooldown_seconds", 60.0),
            context=f"{context}.circuit_cooldown_seconds",
        ),
        max_rationale_chars=_int(
            item.get("max_rationale_chars", 600),
            context=f"{context}.max_rationale_chars",
        ),
        allow_exploration=_bool(
            item.get("allow_exploration", True),
            context=f"{context}.allow_exploration",
        ),
        shadow_mode=_bool(
            item.get("shadow_mode", True),
            context=f"{context}.shadow_mode",
        ),
    )


def _candidate(payload: Any, *, index: int) -> ShadowCandidateSpec:
    context = f"candidates[{index}]"
    item = _mapping(payload, context=context)
    _strict_keys(
        item,
        allowed={"name", "endpoint", "planner_config", "critic_endpoint"},
        required={"name", "endpoint"},
        context=context,
    )
    critic_payload = item.get("critic_endpoint")
    return ShadowCandidateSpec(
        name=_string(item["name"], context=f"{context}.name"),
        endpoint=_endpoint(item["endpoint"], context=f"{context}.endpoint"),
        planner_config=_planner_config(
            item.get("planner_config", {}),
            context=f"{context}.planner_config",
        ),
        critic_endpoint=(
            _endpoint(critic_payload, context=f"{context}.critic_endpoint")
            if critic_payload is not None
            else None
        ),
    )


@dataclass(frozen=True, slots=True)
class ProductionOperatorManifest:
    """Pre-registered, non-secret operator contract for a locked LLM shadow run.

    The manifest deliberately contains no credentials and never embeds causal
    labels. Candidate identity, benchmark gates and evidence-producer identity
    can therefore be reviewed and fingerprinted before provider SDKs or final
    holdout evidence are available.
    """

    benchmark: str
    dataset: str
    dataset_source: str
    candidates: tuple[ShadowCandidateSpec, ...]
    evidence_producer_name: str
    evidence_producer_version: str
    trials_per_case: int = 1
    z_value: float = 1.96
    min_decision_coverage: float = 1.0
    max_invalid_rate: float = 0.0
    max_evidence_violation_rate: float = 0.0
    max_hard_stop_violation_rate: float = 0.0
    max_fallback_rate: float = 0.25
    min_support_coverage: float = 0.95
    min_effective_sample_ratio: float = 0.05
    require_promotion_evidence: bool = True
    evidence_contract: str = "tiered-causal-option-evidence-v1"
    schema_version: str = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(
                f"unsupported production operator schema: {self.schema_version}"
            )
        for name, value in (
            ("benchmark", self.benchmark),
            ("dataset", self.dataset),
            ("dataset_source", self.dataset_source),
            ("evidence_producer_name", self.evidence_producer_name),
            ("evidence_producer_version", self.evidence_producer_version),
            ("evidence_contract", self.evidence_contract),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")
        if not self.candidates:
            raise ValueError("operator manifest requires at least one candidate")

        # Constructing the typed plan here is intentional: all numeric gates,
        # candidate uniqueness and shadow-only posture are validated at manifest
        # creation time, before any remote model can be called.
        _ = self.shadow_plan

    @property
    def llm_plan(self) -> LLMExperimentPlan:
        return LLMExperimentPlan(
            benchmark=self.benchmark,
            dataset=self.dataset,
            dataset_source=self.dataset_source,
            candidates=tuple(
                shadow_candidate_metadata(spec) for spec in self.candidates
            ),
            trials_per_case=self.trials_per_case,
            z_value=self.z_value,
            min_decision_coverage=self.min_decision_coverage,
            max_invalid_rate=self.max_invalid_rate,
            max_evidence_violation_rate=self.max_evidence_violation_rate,
            max_hard_stop_violation_rate=self.max_hard_stop_violation_rate,
            max_fallback_rate=self.max_fallback_rate,
            min_support_coverage=self.min_support_coverage,
            min_effective_sample_ratio=self.min_effective_sample_ratio,
        )

    @property
    def shadow_plan(self) -> ShadowBenchmarkPlan:
        return ShadowBenchmarkPlan(
            llm_plan=self.llm_plan,
            require_promotion_evidence=self.require_promotion_evidence,
            evidence_contract=self.evidence_contract,
        )

    def canonical_payload(self) -> dict[str, Any]:
        plan = self.llm_plan
        shadow = self.shadow_plan
        return {
            "schema_version": self.schema_version,
            "llm_plan": plan.canonical_payload(),
            "llm_plan_fingerprint": plan.fingerprint,
            "shadow_plan_fingerprint": shadow.fingerprint,
            "require_promotion_evidence": self.require_promotion_evidence,
            "evidence_contract": self.evidence_contract,
            "evidence_producer": {
                "name": self.evidence_producer_name,
                "version": self.evidence_producer_version,
            },
        }

    @property
    def fingerprint(self) -> str:
        return fingerprint_json(self.canonical_payload())

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ProductionOperatorManifest":
        _strict_keys(
            payload,
            allowed={
                "schema_version",
                "benchmark",
                "dataset",
                "dataset_source",
                "candidates",
                "evidence_producer",
                "trials_per_case",
                "z_value",
                "min_decision_coverage",
                "max_invalid_rate",
                "max_evidence_violation_rate",
                "max_hard_stop_violation_rate",
                "max_fallback_rate",
                "min_support_coverage",
                "min_effective_sample_ratio",
                "require_promotion_evidence",
                "evidence_contract",
            },
            required={
                "schema_version",
                "benchmark",
                "dataset",
                "dataset_source",
                "candidates",
                "evidence_producer",
            },
            context="operator manifest",
        )
        schema = _string(payload["schema_version"], context="schema_version")
        if schema != _SCHEMA_VERSION:
            raise ValueError(f"unsupported production operator schema: {schema}")

        raw_candidates = payload["candidates"]
        if isinstance(raw_candidates, (str, bytes)) or not isinstance(
            raw_candidates, Sequence
        ):
            raise ValueError("candidates must be a JSON array")
        candidates = tuple(
            _candidate(item, index=index)
            for index, item in enumerate(raw_candidates)
        )

        producer = _mapping(
            payload["evidence_producer"],
            context="evidence_producer",
        )
        _strict_keys(
            producer,
            allowed={"name", "version"},
            required={"name", "version"},
            context="evidence_producer",
        )

        return cls(
            schema_version=schema,
            benchmark=_string(payload["benchmark"], context="benchmark"),
            dataset=_string(payload["dataset"], context="dataset"),
            dataset_source=_string(
                payload["dataset_source"],
                context="dataset_source",
            ),
            candidates=candidates,
            evidence_producer_name=_string(
                producer["name"],
                context="evidence_producer.name",
            ),
            evidence_producer_version=_string(
                producer["version"],
                context="evidence_producer.version",
            ),
            trials_per_case=_int(
                payload.get("trials_per_case", 1),
                context="trials_per_case",
            ),
            z_value=_number(payload.get("z_value", 1.96), context="z_value"),
            min_decision_coverage=_number(
                payload.get("min_decision_coverage", 1.0),
                context="min_decision_coverage",
            ),
            max_invalid_rate=_number(
                payload.get("max_invalid_rate", 0.0),
                context="max_invalid_rate",
            ),
            max_evidence_violation_rate=_number(
                payload.get("max_evidence_violation_rate", 0.0),
                context="max_evidence_violation_rate",
            ),
            max_hard_stop_violation_rate=_number(
                payload.get("max_hard_stop_violation_rate", 0.0),
                context="max_hard_stop_violation_rate",
            ),
            max_fallback_rate=_number(
                payload.get("max_fallback_rate", 0.25),
                context="max_fallback_rate",
            ),
            min_support_coverage=_number(
                payload.get("min_support_coverage", 0.95),
                context="min_support_coverage",
            ),
            min_effective_sample_ratio=_number(
                payload.get("min_effective_sample_ratio", 0.05),
                context="min_effective_sample_ratio",
            ),
            require_promotion_evidence=_bool(
                payload.get("require_promotion_evidence", True),
                context="require_promotion_evidence",
            ),
            evidence_contract=_string(
                payload.get(
                    "evidence_contract",
                    "tiered-causal-option-evidence-v1",
                ),
                context="evidence_contract",
            ),
        )


def load_operator_manifest(path: str | Path) -> ProductionOperatorManifest:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        payload = load(handle)
    return ProductionOperatorManifest.from_mapping(
        _mapping(payload, context=f"operator manifest {source}")
    )


def operator_manifest_schema_version() -> str:
    return _SCHEMA_VERSION
