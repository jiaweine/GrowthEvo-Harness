from __future__ import annotations

import importlib.util
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_frozen_environment.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_frozen_environment", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_exact_pins_skips_editable_and_comments(tmp_path: Path) -> None:
    module = _load_module()
    snapshot = tmp_path / "environment.txt"
    snapshot.write_text(
        "# frozen runtime\n"
        "numpy==1.26.4\n"
        "-e git+https://example.invalid/repo@abc#egg=package\n"
        "torch==2.13.0+cpu\n",
        encoding="utf-8",
    )

    assert module.load_exact_pins(snapshot) == {
        "numpy": "1.26.4",
        "torch": "2.13.0+cpu",
    }


def test_load_exact_pins_rejects_non_exact_requirements(tmp_path: Path) -> None:
    module = _load_module()
    snapshot = tmp_path / "environment.txt"
    snapshot.write_text("numpy>=1.26\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected an exact"):
        module.load_exact_pins(snapshot)


def test_find_mismatches_reports_missing_and_wrong_versions() -> None:
    module = _load_module()
    installed = {"numpy": "1.26.4", "torch": "2.12.0+cpu"}

    def lookup(name: str) -> str:
        if name not in installed:
            raise PackageNotFoundError(name)
        return installed[name]

    mismatches = module.find_mismatches(
        {
            "numpy": "1.26.4",
            "torch": "2.13.0+cpu",
            "obp": "0.4.1",
        },
        lookup=lookup,
    )

    assert mismatches == [
        "obp: missing (expected 0.4.1)",
        "torch: installed 2.12.0+cpu, expected 2.13.0+cpu",
    ]


def test_find_unexpected_distributions_rejects_only_external_extras() -> None:
    module = _load_module()

    unexpected = module.find_unexpected_distributions(
        {
            "numpy": "1.26.4",
            "PyYAML": "6.0.3",
        },
        installed_names={
            "NumPy",
            "pyyaml",
            "pip",
            "growthevo_harness",
            "rogue_pkg",
        },
    )

    assert unexpected == ["rogue-pkg"]


def test_find_unexpected_distributions_can_extend_explicit_allowlist() -> None:
    module = _load_module()

    unexpected = module.find_unexpected_distributions(
        {"numpy": "1.26.4"},
        installed_names={"numpy", "pip", "build-helper"},
        allowed_extra={"pip", "growthevo-harness", "build_helper"},
    )

    assert unexpected == []
