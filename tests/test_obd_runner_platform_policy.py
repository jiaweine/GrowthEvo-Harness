from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_obd_regression_and_trusted_cache_seed_share_ubuntu_2404() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    seed = (WORKFLOWS / "obd-cache-seed.yml").read_text(encoding="utf-8")

    core_ci, obd_ci = ci.split("  obd-integration:\n", maxsplit=1)

    # Compatibility/package jobs intentionally follow GitHub's latest Linux image.
    assert core_ci.count("runs-on: ubuntu-latest") == 2

    # The regression-only evidence path and its trusted cache producer are stable.
    assert "runs-on: ubuntu-24.04" in obd_ci
    assert "runs-on: ubuntu-latest" not in obd_ci
    assert "runs-on: ubuntu-24.04" in seed
    assert "runs-on: ubuntu-latest" not in seed

    cache_identity = ".github/cache/obd-pip-cache-v1.txt"
    bootstrap = "scripts/bootstrap_obd_ci_environment.py"
    for workflow in (obd_ci, seed):
        assert 'python-version: "3.12"' in workflow
        assert cache_identity in workflow
        assert bootstrap in workflow
