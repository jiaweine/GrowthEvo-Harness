from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from json import dumps, loads
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

from growthevo.models import Channel


_SCHEMA_VERSION = "growthevo.targeting-experiment-plan.v1"


@dataclass(frozen=True, slots=True)
class TargetingExperimentPlan:
    """Pre-register upstream choices for a locked randomized-targeting run."""

    benchmark: str
    dataset: str
    dataset_source: str
    outcome_definition: str
    split_strategy: str
    validation_fraction: float
    treatment: Channel
    selected_fraction: float
    score_protocol: str
    candidate_names: tuple[str, ...]
    schema_version: str = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("benchmark", self.benchmark),
            ("dataset", self.dataset),
            ("dataset_source", self.dataset_source),
            ("outcome_definition", self.outcome_definition),
            ("split_strategy", self.split_strategy),
            ("score_protocol", self.score_protocol),
        ):
            if not value:
                raise ValueError(f"{name} cannot be empty")
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(f"unsupported targeting experiment plan schema: {self.schema_version}")
        if self.treatment is Channel.NO_TREATMENT:
            raise ValueError("targeting treatment cannot be NO_TREATMENT")
        if not isfinite(self.validation_fraction) or not 0.0 < self.validation_fraction < 1.0:
            raise ValueError("validation_fraction must be finite and in (0, 1)")
        if not isfinite(self.selected_fraction) or not 0.0 < self.selected_fraction <= 1.0:
            raise ValueError("selected_fraction must be finite and in (0, 1]")
        if not self.candidate_names:
            raise ValueError("targeting plan requires at least one candidate")
        if any(not name for name in self.candidate_names):
            raise ValueError("targeting candidate names cannot be empty")
        if len(set(self.candidate_names)) != len(self.candidate_names):
            raise ValueError("targeting candidate names must be unique")

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark": self.benchmark,
            "dataset": self.dataset,
            "dataset_source": self.dataset_source,
            "outcome_definition": self.outcome_definition,
            "split_strategy": self.split_strategy,
            "validation_fraction": self.validation_fraction,
            "treatment": self.treatment.value,
            "selected_fraction": self.selected_fraction,
            "score_protocol": self.score_protocol,
            "candidate_names": sorted(self.candidate_names),
        }

    @property
    def fingerprint(self) -> str:
        encoded = dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return blake2b(encoded, digest_size=20).hexdigest()

    def bind_protocol_fingerprint(self, locked_protocol_fingerprint: str) -> str:
        if not locked_protocol_fingerprint:
            raise ValueError("locked_protocol_fingerprint cannot be empty")
        encoded = dumps(
            {
                "schema": "growthevo.bound-targeting-protocol.v1",
                "experiment_plan_fingerprint": self.fingerprint,
                "locked_protocol_fingerprint": locked_protocol_fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return blake2b(encoded, digest_size=20).hexdigest()

    def validate_runtime_contract(
        self,
        *,
        benchmark: str,
        dataset: str,
        treatment: Channel,
        selected_fraction: float,
        candidate_names: Sequence[str],
    ) -> None:
        mismatches: list[str] = []
        if benchmark != self.benchmark:
            mismatches.append("benchmark")
        if dataset != self.dataset:
            mismatches.append("dataset")
        if treatment != self.treatment:
            mismatches.append("treatment")
        if selected_fraction != self.selected_fraction:
            mismatches.append("selected_fraction")
        if tuple(sorted(candidate_names)) != tuple(sorted(self.candidate_names)):
            mismatches.append("candidate_names")
        if mismatches:
            raise ValueError(
                "runtime targeting contract does not match pre-registered plan: "
                + ", ".join(mismatches)
            )

    def validate_export_manifest(self, manifest: Mapping[str, Any]) -> None:
        if manifest.get("schema_version") != "growthevo.targeting-export.v1":
            raise ValueError(
                "targeting export manifest does not match pre-registered plan: schema_version"
            )
        expected: tuple[tuple[str, Any], ...] = (
            ("dataset_source", self.dataset_source),
            ("outcome_definition", self.outcome_definition),
            ("split_strategy", self.split_strategy),
            ("validation_fraction", self.validation_fraction),
            ("treatment", self.treatment.value),
            ("score_protocol", self.score_protocol),
        )
        mismatches: list[str] = []
        for key, planned in expected:
            if key not in manifest:
                mismatches.append(f"missing:{key}")
                continue
            observed = manifest[key]
            if isinstance(planned, float):
                if isinstance(observed, bool) or not isinstance(observed, (int, float)):
                    mismatches.append(key)
                elif not isfinite(float(observed)) or float(observed) != planned:
                    mismatches.append(key)
            elif observed != planned:
                mismatches.append(key)
        raw_names = manifest.get("candidate_names")
        if not isinstance(raw_names, list) or any(
            not isinstance(name, str) or not name for name in raw_names
        ):
            mismatches.append("candidate_names")
        elif sorted(raw_names) != sorted(self.candidate_names):
            mismatches.append("candidate_names")
        if mismatches:
            raise ValueError(
                "targeting export manifest does not match pre-registered plan: "
                + ", ".join(mismatches)
            )


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"targeting plan field {key!r} must be a non-empty string")
    return value


def _number(payload: Mapping[str, Any], key: str) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"targeting plan field {key!r} must be a JSON number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"targeting plan field {key!r} must be finite")
    return result


def load_targeting_experiment_plan(path: str | Path) -> TargetingExperimentPlan:
    resolved = Path(path)
    try:
        payload = loads(resolved.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"invalid targeting experiment plan JSON: {resolved}") from exc
    if not isinstance(payload, dict):
        raise ValueError("targeting experiment plan JSON must be an object")
    required = {
        "schema_version",
        "benchmark",
        "dataset",
        "dataset_source",
        "outcome_definition",
        "split_strategy",
        "validation_fraction",
        "treatment",
        "selected_fraction",
        "score_protocol",
        "candidate_names",
    }
    missing = required.difference(payload)
    unknown = set(payload).difference(required)
    if missing:
        raise ValueError(f"targeting experiment plan is missing fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"targeting experiment plan has unknown fields: {sorted(unknown)}")
    raw_names = payload["candidate_names"]
    if not isinstance(raw_names, list) or not raw_names:
        raise ValueError("targeting plan candidate_names must be a non-empty array")
    if any(not isinstance(name, str) or not name for name in raw_names):
        raise ValueError("targeting plan candidate_names must contain non-empty strings")
    try:
        treatment = Channel(_string(payload, "treatment"))
    except ValueError as exc:
        raise ValueError("targeting plan treatment is not a supported Channel") from exc
    return TargetingExperimentPlan(
        schema_version=_string(payload, "schema_version"),
        benchmark=_string(payload, "benchmark"),
        dataset=_string(payload, "dataset"),
        dataset_source=_string(payload, "dataset_source"),
        outcome_definition=_string(payload, "outcome_definition"),
        split_strategy=_string(payload, "split_strategy"),
        validation_fraction=_number(payload, "validation_fraction"),
        treatment=treatment,
        selected_fraction=_number(payload, "selected_fraction"),
        score_protocol=_string(payload, "score_protocol"),
        candidate_names=tuple(raw_names),
    )
