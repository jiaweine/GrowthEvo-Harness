from __future__ import annotations

import json
from pathlib import Path

from growthevo.bench.ope_experiment_plan import load_ope_experiment_plan


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "benchmarks" / "ope" / "development" / "obd-small-all-random-to-bts.v1.json"
PLAN = ROOT / "benchmarks" / "ope" / "obd-small-all-random-to-bts.v1.json"


def _registry() -> dict[str, object]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_small_obd_development_cohort_is_bound_to_plan() -> None:
    registry = _registry()
    plan = load_ope_experiment_plan(PLAN)

    assert registry["schema_version"] == "growthevo.ope-development-cohort.v1"
    assert registry["status"] == "exhausted"
    assert registry["promotion_eligible"] is False
    assert registry["base_plan"] == "benchmarks/ope/obd-small-all-random-to-bts.v1.json"
    assert registry["base_plan_fingerprint"] == plan.fingerprint
    assert registry["validation_reference"] == 0.005

    allowed = set(registry["allowed_future_uses"])
    prohibited = set(registry["prohibited_future_uses"])
    assert {"regression_testing", "integration_testing"}.issubset(allowed)
    assert {
        "new_estimator_promotion",
        "new_q_backend_promotion",
        "new_hyperparameter_promotion",
        "new_candidate_grid_promotion",
    }.issubset(prohibited)


def test_small_obd_attempt_ledger_is_unique_and_holdout_free() -> None:
    attempts = _registry()["attempts"]
    assert isinstance(attempts, list)
    method_ids = [attempt["method_id"] for attempt in attempts]
    assert len(method_ids) == len(set(method_ids))

    recorded_prs: set[int] = set()
    for attempt in attempts:
        assert attempt["decision"] == "rejected"
        assert attempt["holdout_used_for_decision"] is False
        prs = attempt["prs"]
        assert prs
        for pr in prs:
            assert pr not in recorded_prs
            recorded_prs.add(pr)

    assert {25, 43, 44, 45, 46, 47, 48}.issubset(recorded_prs)


def test_small_obd_identity_remains_ci_integration_only() -> None:
    workflows = ROOT / ".github" / "workflows"
    plan_token = "obd-small-all-random-to-bts.v1.json"
    source_token = ":obd-small"

    ci_text = (workflows / "ci.yml").read_text(encoding="utf-8")
    assert plan_token in ci_text
    assert source_token in ci_text
    assert "obd-integration" in ci_text

    offenders: list[str] = []
    for path in sorted(workflows.glob("*.y*ml")):
        if path.name == "ci.yml":
            continue
        text = path.read_text(encoding="utf-8")
        if plan_token in text or source_token in text:
            offenders.append(path.name)
    assert offenders == [], (
        "the small-OBD regression identity may only remain in the normal CI "
        f"integration job; promotion/development workflows found: {offenders}"
    )


def test_governance_docs_require_fresh_identity_for_new_promotion_research() -> None:
    governance = (ROOT / "docs" / "OPE_DEVELOPMENT_GOVERNANCE.md").read_text(
        encoding="utf-8"
    )
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    rerun = (ROOT / "docs" / "RESEARCH_RERUN_POLICY.md").read_text(encoding="utf-8")

    assert "regression and integration cohort" in governance
    assert "fresh preregistered development identity" in governance
    assert "regression and integration baseline" in contributing
    assert "fresh preregistered development identity" in contributing
    assert "fresh preregistered development identity" in rerun
