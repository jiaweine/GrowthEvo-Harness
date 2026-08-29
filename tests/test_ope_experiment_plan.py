from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from growthevo.bench.locked_evaluation import OPECandidate
from growthevo.bench.ope_evidence_gate import OPEEvidenceGate
from growthevo.bench.ope_experiment_plan import load_ope_experiment_plan


_ROOT = Path(__file__).resolve().parents[1]
_SMALL_PLAN = _ROOT / "benchmarks" / "ope" / "obd-small-all-random-to-bts.v1.json"


def test_repository_small_obd_plan_is_strict_and_stable() -> None:
    plan = load_ope_experiment_plan(_SMALL_PLAN)

    assert plan.benchmark == "open-bandit-ope-small-evidence"
    assert plan.dataset == "obd-small-all-random-to-bts"
    assert plan.dataset_source.endswith(
        "1c6d14677ec6f06094a2f8886a1158bab99c571e:obd-small"
    )
    assert plan.q_model == "logistic"
    assert plan.q_folds == 2
    assert plan.n_sim == 500
    assert plan.evidence_gate == OPEEvidenceGate(
        min_support_coverage=0.95,
        min_effective_sample_ratio=0.05,
        require_positive_importance_mass=True,
    )
    assert len(plan.fingerprint) == 40
    assert plan.fingerprint == load_ope_experiment_plan(_SMALL_PLAN).fingerprint


def test_plan_rejects_json_bool_as_integer_and_unknown_candidate_fields(tmp_path: Path) -> None:
    payload = json.loads(_SMALL_PLAN.read_text(encoding="utf-8"))
    payload["q_folds"] = True
    broken = tmp_path / "bool-int.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="q_folds.*JSON integer"):
        load_ope_experiment_plan(broken)

    payload = json.loads(_SMALL_PLAN.read_text(encoding="utf-8"))
    payload["candidates"][0]["hidden_tuning_knob"] = 1
    broken = tmp_path / "unknown-candidate-field.json"
    broken.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown fields"):
        load_ope_experiment_plan(broken)


def test_plan_validates_runtime_and_realized_export_manifest() -> None:
    plan = load_ope_experiment_plan(_SMALL_PLAN)
    manifest = {
        "schema_version": "growthevo.obd-export.v2",
        "dataset_source": plan.dataset_source,
        "campaign": plan.campaign,
        "behavior_policy": plan.behavior_policy,
        "evaluation_policy": plan.evaluation_policy,
        "reward_definition": plan.reward_definition,
        "split_strategy": plan.split_strategy,
        "validation_fraction": plan.validation_fraction,
        "q_model": plan.q_model,
        "q_folds": plan.q_folds,
        "n_sim": plan.n_sim,
        "random_state": plan.random_state,
    }

    plan.validate_runtime_contract(
        benchmark=plan.benchmark,
        dataset=plan.dataset,
        candidates=plan.candidates,
        support_propensity_floor=plan.support_propensity_floor,
        evidence_gate=plan.evidence_gate,
    )
    plan.validate_export_manifest(manifest)

    with pytest.raises(ValueError, match="n_sim"):
        plan.validate_export_manifest({**manifest, "n_sim": plan.n_sim + 1})

    with pytest.raises(ValueError, match="schema_version"):
        plan.validate_export_manifest({**manifest, "schema_version": "legacy"})


def test_plan_fingerprint_binds_gate_candidates_and_source() -> None:
    plan = load_ope_experiment_plan(_SMALL_PLAN)
    changed_gate = replace(
        plan,
        evidence_gate=OPEEvidenceGate(
            min_support_coverage=0.96,
            min_effective_sample_ratio=0.05,
            require_positive_importance_mass=True,
        ),
    )
    changed_source = replace(plan, dataset_source=plan.dataset_source + "-changed")
    changed_candidates = replace(
        plan,
        candidates=(OPECandidate(name="ips-only", estimator="ips"),),
    )

    assert changed_gate.fingerprint != plan.fingerprint
    assert changed_source.fingerprint != plan.fingerprint
    assert changed_candidates.fingerprint != plan.fingerprint
