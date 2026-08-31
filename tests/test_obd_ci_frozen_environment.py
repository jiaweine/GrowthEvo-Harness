from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_obd_ci_environment.py"
ACCEPTED_ENVIRONMENT = (
    ROOT
    / "benchmarks"
    / "ope"
    / "results"
    / "obd-full-all-random-to-bts"
    / "7d538cea"
    / "environment.txt"
)


def test_small_obd_ci_uses_the_accepted_full_obd_third_party_environment() -> None:
    bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
    accepted = ACCEPTED_ENVIRONMENT.read_text(encoding="utf-8")

    assert "torch==2.13.0+cpu" in accepted
    assert "obp==0.4.1" in accepted
    assert "sb-obp==0.5.10" in accepted
    assert "joblib==1.5.3" in accepted
    assert "scipy==1.17.1" in accepted
    assert "cloudpickle==" not in accepted

    assert "ACCEPTED_OBD_ENVIRONMENT" in bootstrap
    assert '"obd-full-all-random-to-bts"' in bootstrap
    assert '"7d538cea"' in bootstrap
    assert "load_exact_pins(snapshot)" in bootstrap
    assert "write_constraints(snapshot, CONSTRAINTS_OUTPUT)" in bootstrap
    assert bootstrap.count('"--constraint"') >= 3
    assert "find_mismatches(pins)" in bootstrap
    assert "Frozen OBD environment mismatch" in bootstrap
