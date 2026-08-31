from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_small_obd_ci_enforces_and_persists_regression_contract() -> None:
    workflow = CI.read_text(encoding="utf-8")
    _, obd = workflow.split("  obd-integration:\n", maxsplit=1)

    contract = "benchmarks/ope/obd-small-regression-contract.v1.json"
    validator = "scripts/validate_obd_regression_contract.py"

    assert f"OBD_REGRESSION_CONTRACT: {contract}" in obd
    assert "- name: Enforce small OBD regression contract" in obd
    assert f"python {validator}" in obd
    assert '--contract "$OBD_REGRESSION_CONTRACT"' in obd
    assert "--result /tmp/growthevo-obd/locked-result.json" in obd

    upload = obd.split("- name: Upload locked OBD evidence summary", maxsplit=1)[1]
    assert contract in upload
    assert "/tmp/growthevo-obd-runtime.json" in upload
    assert "/tmp/growthevo-obd/locked-result.json" in upload
