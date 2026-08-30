from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_SHA = "5fda3b95a4ea91299a34e894583c3862153e4b97"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
ACTION_REF = re.compile(r"^\s*uses:\s+([^\s@]+)@([^\s#]+)", re.MULTILINE)


def _assert_external_actions_are_immutable(workflow: str) -> None:
    refs = ACTION_REF.findall(workflow)
    assert refs
    for action, ref in refs:
        if action.startswith("./"):
            continue
        assert re.fullmatch(r"[0-9a-f]{40}", ref), f"{action}@{ref} is not immutable"


def test_regular_ci_uses_immutable_node24_native_actions_and_builds_distribution() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    _assert_external_actions_are_immutable(ci)
    assert f"actions/checkout@{CHECKOUT_SHA} # v7" in ci
    assert f"actions/setup-python@{SETUP_PYTHON_SHA} # v7" in ci
    assert f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v7" in ci
    assert "actions/checkout@v7" not in ci
    assert "actions/setup-python@v7" not in ci
    assert "actions/upload-artifact@v7" not in ci
    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in ci
    assert 'python-version: "3.14"' in ci
    assert "  package:\n" in ci
    assert "python -m build" in ci
    assert "python -m twine check dist/*" in ci
    assert "growthevo-locked-ope --help" in ci
    assert "growthevo-locked-targeting --help" in ci


def test_small_obd_ci_preinstalls_cpu_only_torch_before_obd_extra() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    cpu_index = "https://download.pytorch.org/whl/cpu"
    cpu_torch = "torch==2.13.0+cpu"
    obd_install = "pip install -e '.[obd]'"

    assert "Install GrowthEvo with CPU-only OBD bridge" in ci
    assert cpu_index in ci
    assert cpu_torch in ci
    assert "assert not torch.cuda.is_available()" in ci
    assert ci.index(cpu_torch) < ci.index(obd_install)


def test_accepted_full_data_workflows_are_manual_only_and_sha_pinned() -> None:
    for filename in (
        "full-criteo-pr-validation.yml",
        "full-obd-pr-validation.yml",
    ):
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert "workflow_dispatch:" in workflow
        assert "experiment_reason:" in workflow
        assert "pull_request:" not in workflow
        assert "cancel-in-progress: false" in workflow
        _assert_external_actions_are_immutable(workflow)
        assert f"actions/checkout@{CHECKOUT_SHA} # v7" in workflow
        assert f"actions/setup-python@{SETUP_PYTHON_SHA} # v7" in workflow
        assert f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v7" in workflow
