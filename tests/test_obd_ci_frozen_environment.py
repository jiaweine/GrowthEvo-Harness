from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BOOTSTRAP = SCRIPTS / "bootstrap_obd_ci_environment.py"
ACCEPTED_ENVIRONMENT = (
    ROOT
    / "benchmarks"
    / "ope"
    / "results"
    / "obd-full-all-random-to-bts"
    / "7d538cea"
    / "environment.txt"
)


def _load_bootstrap():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("bootstrap_obd_ci_environment", BOOTSTRAP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def test_frozen_obd_constraints_are_exact_and_skip_editable_source(tmp_path: Path) -> None:
    module = _load_bootstrap()
    output = tmp_path / "constraints.txt"

    count = module.write_constraints(ACCEPTED_ENVIRONMENT, output)
    constraints = output.read_text(encoding="utf-8")

    assert count > 20
    assert "-e " not in constraints
    assert "torch==2.13.0+cpu" in constraints
    assert "obp==0.4.1" in constraints
    assert "sb-obp==0.5.10" in constraints
    assert "joblib==1.5.3" in constraints
    assert "cloudpickle==" not in constraints
    for line in constraints.splitlines():
        assert line.count("==") == 1
