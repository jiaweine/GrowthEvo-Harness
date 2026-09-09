from __future__ import annotations

import json
from pathlib import Path

import pytest

from growthevo.operator_shadow import (
    DeferredFileCausalEvidenceProducer,
    context_fingerprints,
    load_context_specs,
)


def _case(case_id: str) -> dict:
    return {
        "case_id": case_id,
        "belief": {
            "user_id": f"user-{case_id}",
            "natural_conversion": 0.10,
            "channel_uplift": {"email": 0.03, "push": 0.02},
            "uplift_uncertainty": 0.10,
            "ltv": 100.0,
            "fatigue": 0.10,
            "churn_risk": 0.35,
            "touches_24h": 0,
            "touches_7d": 1,
            "spend_to_date": 0.0,
            "days_since_last_active": 2,
            "lifecycle_stage": "active",
            "consented_channels": ["email", "push"],
        },
        "goal": {
            "metric": "incremental_ltv",
            "horizon_days": 30,
            "target_delta": 0.05,
            "constraints": {"max_budget": 10.0},
        },
        "baseline_option": "retain",
        "weight": 1.0,
    }


def _write_context(path: Path, case_id: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "growthevo.operator-contexts.v1",
                "cases": [_case(case_id)],
            }
        ),
        encoding="utf-8",
    )


def _write_evidence(
    path: Path,
    *,
    case_id: str,
    context_fingerprint: str,
    producer_name: str = "test-evidence",
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "growthevo.operator-causal-evidence.v1",
                "producer": {"name": producer_name, "version": "v1"},
                "bundles": [
                    {
                        "case_id": case_id,
                        "context_fingerprint": context_fingerprint,
                        "estimand": "incremental value vs no treatment",
                        "estimates": [
                            {
                                "option": "retain",
                                "value": 0.01,
                                "standard_error": 0.001,
                                "tier": "tier_a_randomized_experiment",
                                "source_id": f"experiment:{case_id}",
                                "protocol_fingerprint": "protocol-v1",
                                "support_coverage": 1.0,
                                "effective_sample_ratio": 0.8,
                                "feasible": True,
                                "sample_size": 1000,
                            },
                            {
                                "option": "upsell",
                                "value": 0.03,
                                "standard_error": 0.001,
                                "tier": "tier_a_randomized_experiment",
                                "source_id": f"experiment:{case_id}",
                                "protocol_fingerprint": "protocol-v1",
                                "support_coverage": 1.0,
                                "effective_sample_ratio": 0.8,
                                "feasible": True,
                                "sample_size": 1000,
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_deferred_evidence_never_opens_holdout_before_requested(tmp_path: Path) -> None:
    validation_context = tmp_path / "validation-context.json"
    holdout_context = tmp_path / "holdout-context.json"
    _write_context(validation_context, "validation-1")
    _write_context(holdout_context, "holdout-1")

    validation_specs = load_context_specs(validation_context)
    holdout_specs = load_context_specs(holdout_context)
    validation_evidence = tmp_path / "validation-evidence.json"
    holdout_evidence = tmp_path / "holdout-evidence.json"
    _write_evidence(
        validation_evidence,
        case_id="validation-1",
        context_fingerprint=validation_specs[0].context_fingerprint,
    )
    _write_evidence(
        holdout_evidence,
        case_id="holdout-1",
        context_fingerprint=holdout_specs[0].context_fingerprint,
    )

    producer = DeferredFileCausalEvidenceProducer(
        validation_path=validation_evidence,
        holdout_path=holdout_evidence,
        validation_case_ids=("validation-1",),
        holdout_case_ids=("holdout-1",),
        name="test-evidence",
        version="v1",
    )

    assert producer.loaded_splits == ()
    validation_bundle = producer.produce(validation_specs[0])
    assert validation_bundle.case_id == "validation-1"
    assert producer.loaded_splits == ("validation",)

    holdout_bundle = producer.produce(holdout_specs[0])
    assert holdout_bundle.case_id == "holdout-1"
    assert producer.loaded_splits == ("validation", "holdout")


def test_context_fingerprints_are_reviewable_and_stable(tmp_path: Path) -> None:
    context = tmp_path / "contexts.json"
    _write_context(context, "case-1")
    specs = load_context_specs(context)

    fingerprints = context_fingerprints(specs)
    assert fingerprints[0].case_id == "case-1"
    assert len(fingerprints[0].context_fingerprint) == 40
    assert fingerprints[0].context_fingerprint == specs[0].context_fingerprint


def test_evidence_producer_identity_must_match_manifest_contract(tmp_path: Path) -> None:
    context = tmp_path / "contexts.json"
    _write_context(context, "case-1")
    specs = load_context_specs(context)
    validation_evidence = tmp_path / "validation-evidence.json"
    holdout_evidence = tmp_path / "holdout-evidence.json"
    _write_evidence(
        validation_evidence,
        case_id="case-1",
        context_fingerprint=specs[0].context_fingerprint,
        producer_name="wrong-producer",
    )
    _write_evidence(
        holdout_evidence,
        case_id="case-2",
        context_fingerprint="0" * 40,
    )

    producer = DeferredFileCausalEvidenceProducer(
        validation_path=validation_evidence,
        holdout_path=holdout_evidence,
        validation_case_ids=("case-1",),
        holdout_case_ids=("case-2",),
        name="test-evidence",
        version="v1",
    )

    with pytest.raises(ValueError, match="producer identity"):
        producer.produce(specs[0])
