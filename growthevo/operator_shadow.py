from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from json import load
from math import isfinite
from pathlib import Path
from typing import Any

from growthevo.bench.causal_evidence import (
    CausalEvidenceBundle,
    CausalOptionEstimate,
    EvidenceCaseSpec,
    EvidenceTier,
)
from growthevo.models import (
    CausalBelief,
    Channel,
    GrowthConstraints,
    GrowthGoal,
    GrowthOption,
    UserObservation,
)


_CONTEXT_SCHEMA = "growthevo.operator-contexts.v1"
_EVIDENCE_SCHEMA = "growthevo.operator-causal-evidence.v1"


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


def _channel(value: Any, *, context: str) -> Channel:
    try:
        return Channel(_string(value, context=context))
    except ValueError as exc:
        raise ValueError(f"{context} is not a valid GrowthEvo channel") from exc


def _option(value: Any, *, context: str) -> GrowthOption:
    try:
        return GrowthOption(_string(value, context=context))
    except ValueError as exc:
        raise ValueError(f"{context} is not a valid GrowthOption") from exc


def _tier(value: Any, *, context: str) -> EvidenceTier:
    try:
        return EvidenceTier(_string(value, context=context))
    except ValueError as exc:
        raise ValueError(f"{context} is not a valid causal evidence tier") from exc


def _constraints(payload: Any, *, context: str) -> GrowthConstraints:
    item = _mapping(payload, context=context)
    _strict_keys(
        item,
        allowed={
            "max_budget",
            "min_roi",
            "max_fatigue",
            "max_churn_risk",
            "max_touches_24h",
            "max_touches_7d",
            "max_offer_value",
        },
        required={"max_budget"},
        context=context,
    )
    return GrowthConstraints(
        max_budget=_number(item["max_budget"], context=f"{context}.max_budget"),
        min_roi=_number(item.get("min_roi", 1.0), context=f"{context}.min_roi"),
        max_fatigue=_number(
            item.get("max_fatigue", 0.8),
            context=f"{context}.max_fatigue",
        ),
        max_churn_risk=_number(
            item.get("max_churn_risk", 0.5),
            context=f"{context}.max_churn_risk",
        ),
        max_touches_24h=_int(
            item.get("max_touches_24h", 2),
            context=f"{context}.max_touches_24h",
        ),
        max_touches_7d=_int(
            item.get("max_touches_7d", 6),
            context=f"{context}.max_touches_7d",
        ),
        max_offer_value=_number(
            item.get("max_offer_value", 20.0),
            context=f"{context}.max_offer_value",
        ),
    )


def _goal(payload: Any, *, context: str) -> GrowthGoal:
    item = _mapping(payload, context=context)
    _strict_keys(
        item,
        allowed={"metric", "horizon_days", "target_delta", "constraints"},
        required={"metric", "horizon_days", "target_delta", "constraints"},
        context=context,
    )
    return GrowthGoal(
        metric=_string(item["metric"], context=f"{context}.metric"),
        horizon_days=_int(
            item["horizon_days"],
            context=f"{context}.horizon_days",
        ),
        target_delta=_number(
            item["target_delta"],
            context=f"{context}.target_delta",
        ),
        constraints=_constraints(
            item["constraints"],
            context=f"{context}.constraints",
        ),
    )


def _belief(payload: Any, *, context: str) -> CausalBelief:
    item = _mapping(payload, context=context)
    required = {
        "user_id",
        "natural_conversion",
        "channel_uplift",
        "uplift_uncertainty",
        "ltv",
        "fatigue",
        "churn_risk",
        "touches_24h",
        "touches_7d",
        "spend_to_date",
        "days_since_last_active",
        "lifecycle_stage",
        "consented_channels",
    }
    _strict_keys(item, allowed=required, required=required, context=context)

    raw_uplift = _mapping(
        item["channel_uplift"],
        context=f"{context}.channel_uplift",
    )
    channel_uplift = {
        _channel(key, context=f"{context}.channel_uplift key"): _number(
            value,
            context=f"{context}.channel_uplift[{key!r}]",
        )
        for key, value in raw_uplift.items()
    }

    raw_consented = item["consented_channels"]
    if isinstance(raw_consented, (str, bytes)) or not isinstance(
        raw_consented, Sequence
    ):
        raise ValueError(f"{context}.consented_channels must be a JSON array")
    consented = frozenset(
        _channel(value, context=f"{context}.consented_channels")
        for value in raw_consented
    )
    if Channel.NO_TREATMENT in consented:
        raise ValueError(
            f"{context}.consented_channels cannot contain no_treatment"
        )

    # UserObservation supplies the runtime validation contract that CausalBelief
    # intentionally does not duplicate.
    observation = UserObservation(
        user_id=_string(item["user_id"], context=f"{context}.user_id"),
        natural_conversion=_number(
            item["natural_conversion"],
            context=f"{context}.natural_conversion",
        ),
        channel_uplift=channel_uplift,
        uplift_uncertainty=_number(
            item["uplift_uncertainty"],
            context=f"{context}.uplift_uncertainty",
        ),
        ltv=_number(item["ltv"], context=f"{context}.ltv"),
        fatigue=_number(item["fatigue"], context=f"{context}.fatigue"),
        churn_risk=_number(
            item["churn_risk"],
            context=f"{context}.churn_risk",
        ),
        touches_24h=_int(
            item["touches_24h"],
            context=f"{context}.touches_24h",
        ),
        touches_7d=_int(
            item["touches_7d"],
            context=f"{context}.touches_7d",
        ),
        spend_to_date=_number(
            item["spend_to_date"],
            context=f"{context}.spend_to_date",
        ),
        days_since_last_active=_int(
            item["days_since_last_active"],
            context=f"{context}.days_since_last_active",
        ),
        lifecycle_stage=_string(
            item["lifecycle_stage"],
            context=f"{context}.lifecycle_stage",
        ),
        consented_channels=consented,
    )
    return CausalBelief(
        user_id=observation.user_id,
        natural_conversion=observation.natural_conversion,
        channel_uplift=observation.channel_uplift,
        uplift_uncertainty=observation.uplift_uncertainty,
        ltv=observation.ltv,
        fatigue=observation.fatigue,
        churn_risk=observation.churn_risk,
        touches_24h=observation.touches_24h,
        touches_7d=observation.touches_7d,
        spend_to_date=observation.spend_to_date,
        days_since_last_active=observation.days_since_last_active,
        lifecycle_stage=observation.lifecycle_stage,
        consented_channels=observation.consented_channels,
    )


def _case(payload: Any, *, index: int) -> EvidenceCaseSpec:
    context = f"cases[{index}]"
    item = _mapping(payload, context=context)
    _strict_keys(
        item,
        allowed={"case_id", "belief", "goal", "baseline_option", "weight"},
        required={"case_id", "belief", "goal", "baseline_option"},
        context=context,
    )
    return EvidenceCaseSpec(
        case_id=_string(item["case_id"], context=f"{context}.case_id"),
        belief=_belief(item["belief"], context=f"{context}.belief"),
        goal=_goal(item["goal"], context=f"{context}.goal"),
        baseline_option=_option(
            item["baseline_option"],
            context=f"{context}.baseline_option",
        ),
        weight=_number(item.get("weight", 1.0), context=f"{context}.weight"),
    )


def load_context_specs(path: str | Path) -> tuple[EvidenceCaseSpec, ...]:
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        payload = _mapping(load(handle), context=f"context file {source}")
    _strict_keys(
        payload,
        allowed={"schema_version", "cases"},
        required={"schema_version", "cases"},
        context=f"context file {source}",
    )
    schema = _string(payload["schema_version"], context="schema_version")
    if schema != _CONTEXT_SCHEMA:
        raise ValueError(f"unsupported operator context schema: {schema}")

    raw_cases = payload["cases"]
    if isinstance(raw_cases, (str, bytes)) or not isinstance(raw_cases, Sequence):
        raise ValueError("cases must be a JSON array")
    specs = tuple(_case(item, index=index) for index, item in enumerate(raw_cases))
    if not specs:
        raise ValueError("context file requires at least one case")
    ids = [spec.case_id for spec in specs]
    if len(set(ids)) != len(ids):
        raise ValueError("context case ids must be unique")
    return specs


def _estimate(payload: Any, *, context: str) -> CausalOptionEstimate:
    item = _mapping(payload, context=context)
    _strict_keys(
        item,
        allowed={
            "option",
            "value",
            "standard_error",
            "tier",
            "source_id",
            "protocol_fingerprint",
            "support_coverage",
            "effective_sample_ratio",
            "feasible",
            "sample_size",
        },
        required={
            "option",
            "value",
            "standard_error",
            "tier",
            "source_id",
            "protocol_fingerprint",
        },
        context=context,
    )
    sample_size = item.get("sample_size")
    return CausalOptionEstimate(
        option=_option(item["option"], context=f"{context}.option"),
        value=_number(item["value"], context=f"{context}.value"),
        standard_error=_number(
            item["standard_error"],
            context=f"{context}.standard_error",
        ),
        tier=_tier(item["tier"], context=f"{context}.tier"),
        source_id=_string(item["source_id"], context=f"{context}.source_id"),
        protocol_fingerprint=_string(
            item["protocol_fingerprint"],
            context=f"{context}.protocol_fingerprint",
        ),
        support_coverage=_number(
            item.get("support_coverage", 1.0),
            context=f"{context}.support_coverage",
        ),
        effective_sample_ratio=_number(
            item.get("effective_sample_ratio", 1.0),
            context=f"{context}.effective_sample_ratio",
        ),
        feasible=_bool(item.get("feasible", True), context=f"{context}.feasible"),
        sample_size=(
            _int(sample_size, context=f"{context}.sample_size")
            if sample_size is not None
            else None
        ),
    )


def _read_evidence_file(
    path: Path,
    *,
    expected_name: str,
    expected_version: str,
) -> dict[str, CausalEvidenceBundle]:
    with path.open("r", encoding="utf-8") as handle:
        payload = _mapping(load(handle), context=f"evidence file {path}")
    _strict_keys(
        payload,
        allowed={"schema_version", "producer", "bundles"},
        required={"schema_version", "producer", "bundles"},
        context=f"evidence file {path}",
    )
    schema = _string(payload["schema_version"], context="schema_version")
    if schema != _EVIDENCE_SCHEMA:
        raise ValueError(f"unsupported operator evidence schema: {schema}")

    producer = _mapping(payload["producer"], context="producer")
    _strict_keys(
        producer,
        allowed={"name", "version"},
        required={"name", "version"},
        context="producer",
    )
    name = _string(producer["name"], context="producer.name")
    version = _string(producer["version"], context="producer.version")
    if (name, version) != (expected_name, expected_version):
        raise ValueError(
            "evidence producer identity does not match the operator manifest"
        )

    raw_bundles = payload["bundles"]
    if isinstance(raw_bundles, (str, bytes)) or not isinstance(
        raw_bundles, Sequence
    ):
        raise ValueError("bundles must be a JSON array")

    bundles: dict[str, CausalEvidenceBundle] = {}
    for index, raw in enumerate(raw_bundles):
        context = f"bundles[{index}]"
        item = _mapping(raw, context=context)
        _strict_keys(
            item,
            allowed={
                "case_id",
                "context_fingerprint",
                "estimand",
                "estimates",
            },
            required={
                "case_id",
                "context_fingerprint",
                "estimand",
                "estimates",
            },
            context=context,
        )
        raw_estimates = item["estimates"]
        if isinstance(raw_estimates, (str, bytes)) or not isinstance(
            raw_estimates, Sequence
        ):
            raise ValueError(f"{context}.estimates must be a JSON array")
        estimates = tuple(
            _estimate(value, context=f"{context}.estimates[{estimate_index}]")
            for estimate_index, value in enumerate(raw_estimates)
        )
        bundle = CausalEvidenceBundle(
            case_id=_string(item["case_id"], context=f"{context}.case_id"),
            context_fingerprint=_string(
                item["context_fingerprint"],
                context=f"{context}.context_fingerprint",
            ),
            estimand=_string(item["estimand"], context=f"{context}.estimand"),
            estimates=estimates,
            producer_name=name,
            producer_version=version,
        )
        if bundle.case_id in bundles:
            raise ValueError(f"duplicate causal evidence case id: {bundle.case_id}")
        bundles[bundle.case_id] = bundle
    if not bundles:
        raise ValueError("evidence file requires at least one bundle")
    return bundles


class DeferredFileCausalEvidenceProducer:
    """Split-aware evidence producer that never opens holdout labels early."""

    def __init__(
        self,
        *,
        validation_path: str | Path,
        holdout_path: str | Path,
        validation_case_ids: Sequence[str],
        holdout_case_ids: Sequence[str],
        name: str,
        version: str,
    ) -> None:
        if not name.strip() or not version.strip():
            raise ValueError("producer name and version cannot be empty")
        self.name = name
        self.version = version
        self._validation_path = Path(validation_path)
        self._holdout_path = Path(holdout_path)
        self._validation_ids = frozenset(validation_case_ids)
        self._holdout_ids = frozenset(holdout_case_ids)
        if not self._validation_ids or not self._holdout_ids:
            raise ValueError("validation and holdout case ids cannot be empty")
        overlap = self._validation_ids.intersection(self._holdout_ids)
        if overlap:
            raise ValueError(
                f"validation and holdout case ids overlap: {sorted(overlap)[:3]}"
            )
        self._loaded: dict[str, dict[str, CausalEvidenceBundle]] = {}
        self._load_order: list[str] = []

    @property
    def loaded_splits(self) -> tuple[str, ...]:
        return tuple(self._load_order)

    def _load_split(self, split: str) -> dict[str, CausalEvidenceBundle]:
        cached = self._loaded.get(split)
        if cached is not None:
            return cached
        if split == "validation":
            path = self._validation_path
            expected_ids = self._validation_ids
        elif split == "holdout":
            path = self._holdout_path
            expected_ids = self._holdout_ids
        else:  # pragma: no cover - private invariant
            raise AssertionError(f"unknown evidence split: {split}")

        bundles = _read_evidence_file(
            path,
            expected_name=self.name,
            expected_version=self.version,
        )
        actual_ids = frozenset(bundles)
        if actual_ids != expected_ids:
            missing = sorted(expected_ids.difference(actual_ids))
            unexpected = sorted(actual_ids.difference(expected_ids))
            raise ValueError(
                f"{split} evidence ids do not match context ids; "
                f"missing={missing[:3]}, unexpected={unexpected[:3]}"
            )
        self._loaded[split] = bundles
        self._load_order.append(split)
        return bundles

    def produce(self, spec: EvidenceCaseSpec) -> CausalEvidenceBundle:
        if spec.case_id in self._validation_ids:
            split = "validation"
        elif spec.case_id in self._holdout_ids:
            split = "holdout"
        else:
            raise KeyError(
                f"case {spec.case_id!r} is not registered in either evidence split"
            )
        bundle = self._load_split(split)[spec.case_id]
        if bundle.context_fingerprint != spec.context_fingerprint:
            raise ValueError("causal evidence context fingerprint does not match case")
        return bundle


@dataclass(frozen=True, slots=True)
class ContextFingerprint:
    case_id: str
    context_fingerprint: str


def context_fingerprints(
    specs: Sequence[EvidenceCaseSpec],
) -> tuple[ContextFingerprint, ...]:
    return tuple(
        ContextFingerprint(
            case_id=spec.case_id,
            context_fingerprint=spec.context_fingerprint,
        )
        for spec in sorted(specs, key=lambda item: item.case_id)
    )


def operator_context_schema_version() -> str:
    return _CONTEXT_SCHEMA


def operator_evidence_schema_version() -> str:
    return _EVIDENCE_SCHEMA
