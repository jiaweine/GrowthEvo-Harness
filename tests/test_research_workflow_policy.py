from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
OBD_BOOTSTRAP = ROOT / "scripts" / "bootstrap_obd_ci_environment.py"
FROZEN_ENV_VERIFIER = ROOT / "scripts" / "verify_frozen_environment.py"
ACCEPTED_FULL_OBD_ENV = (
    ROOT
    / "benchmarks"
    / "ope"
    / "results"
    / "obd-full-all-random-to-bts"
    / "7d538cea"
    / "environment.txt"
)

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


def test_shared_obd_bootstrap_pins_cpu_only_torch_and_known_obp_resolution() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    bootstrap = OBD_BOOTSTRAP.read_text(encoding="utf-8")
    bootstrap_command = "python scripts/bootstrap_obd_ci_environment.py"

    assert "Install GrowthEvo with CPU-only OBD bridge" in ci
    assert bootstrap_command in ci
    assert 'CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"' in bootstrap
    assert 'TORCH_REQUIREMENT = "torch==2.13.0+cpu"' in bootstrap
    assert 'LEGACY_OBP_REQUIREMENT = "obp==0.4.1"' in bootstrap
    assert 'GROWTHEVO_OBD_REQUIREMENT = ".[obd]"' in bootstrap
    assert 'EXPECTED_TORCH_VERSION = "2.13.0+cpu"' in bootstrap
    assert 'EXPECTED_OBP_MODULE_VERSION = "0.5.5"' in bootstrap
    assert 'EXPECTED_SB_OBP_DISTRIBUTION_VERSION = "0.5.10"' in bootstrap
    assert 'EXPECTED_LEGACY_OBP_DISTRIBUTION_VERSION = "0.4.1"' in bootstrap
    assert "assert not cuda_available" in bootstrap
    assert "obp_module_version=" in bootstrap
    assert "sb_obp_distribution=" in bootstrap
    assert "legacy_obp_distribution=" in bootstrap
    assert "growthevo-locked-ope" not in bootstrap
    assert "export_obd_locked_ope.py" not in bootstrap


def test_small_obd_ci_persists_resolved_environment_with_evidence() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    bootstrap = OBD_BOOTSTRAP.read_text(encoding="utf-8")
    environment_path = "/tmp/growthevo-obd-environment.txt"

    assert f"--freeze-output {environment_path}" in ci
    assert '_pip("freeze", stdout=handle)' in bootstrap
    assert "Upload locked OBD evidence summary" in ci
    assert environment_path in ci.split("Upload locked OBD evidence summary", maxsplit=1)[1]


def test_small_obd_ci_uses_a_cache_identity_separate_from_core_python_312() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    cache_identity = ".github/cache/obd-pip-cache-v1.txt"
    bootstrap_path = "scripts/bootstrap_obd_ci_environment.py"
    core_ci, obd_ci = ci.split("  obd-integration:\n", maxsplit=1)

    assert cache_identity not in core_ci
    assert bootstrap_path not in core_ci
    assert "cache-dependency-path: |\n            pyproject.toml\n" in obd_ci
    assert cache_identity in obd_ci
    assert bootstrap_path in obd_ci
    assert (ROOT / cache_identity).read_text(encoding="utf-8").strip().endswith(
        "obd-research-cache-v1"
    )


def test_obd_cache_seed_is_trusted_main_only_and_matches_integration_identity() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    seed = (WORKFLOWS / "obd-cache-seed.yml").read_text(encoding="utf-8")
    cache_identity = ".github/cache/obd-pip-cache-v1.txt"
    bootstrap_path = "scripts/bootstrap_obd_ci_environment.py"
    bootstrap_command = f"python {bootstrap_path}"

    _assert_external_actions_are_immutable(seed)
    assert "  push:\n    branches: [main]\n" in seed
    assert "  workflow_dispatch:\n" in seed
    assert "pull_request:" not in seed
    assert "permissions:\n  contents: read\n" in seed
    assert f"actions/checkout@{CHECKOUT_SHA} # v7" in seed
    assert f"actions/setup-python@{SETUP_PYTHON_SHA} # v7" in seed
    assert "cache-dependency-path: |\n            pyproject.toml\n" in seed
    assert cache_identity in seed
    assert bootstrap_path in seed
    assert f"      - {bootstrap_path}\n" in seed
    assert ".github/workflows/obd-cache-seed.yml" in seed
    assert bootstrap_command in seed
    assert bootstrap_command in ci
    assert "growthevo-locked-ope" not in seed
    assert "export_obd_locked_ope.py" not in seed


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


def test_accepted_full_data_workflows_pin_runner_family_and_persist_platform_provenance() -> None:
    cases = (
        (
            "full-criteo-pr-validation.yml",
            "/tmp/growthevo-full-criteo/runner-environment.txt",
            "Run full preregistered Criteo benchmark",
            "Upload full Criteo research evidence",
        ),
        (
            "full-obd-pr-validation.yml",
            "/tmp/growthevo-full-obd/runner-environment.txt",
            "Run full preregistered Open Bandit benchmark",
            "Upload full OBD research evidence",
        ),
    )
    for filename, provenance_path, benchmark_step, upload_step in cases:
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert "runs-on: ubuntu-24.04" in workflow
        assert "runs-on: ubuntu-latest" not in workflow
        assert 'grep -q \'^VERSION_ID="24.04"$\' /etc/os-release' in workflow
        assert "${RUNNER_OS:-unknown}" in workflow
        assert "${RUNNER_ARCH:-unknown}" in workflow
        assert "${ImageOS:-unknown}" in workflow
        assert "${ImageVersion:-unknown}" in workflow
        assert "uname -a" in workflow
        assert "ldd --version" in workflow
        assert provenance_path in workflow
        assert workflow.index(provenance_path) < workflow.index(benchmark_step)
        assert provenance_path in workflow.split(upload_step, maxsplit=1)[1]


def test_full_obd_replication_is_constrained_to_the_accepted_environment() -> None:
    workflow = (WORKFLOWS / "full-obd-pr-validation.yml").read_text(encoding="utf-8")
    accepted = ACCEPTED_FULL_OBD_ENV.read_text(encoding="utf-8")
    accepted_path = (
        "benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/environment.txt"
    )
    constraints_path = "/tmp/growthevo-full-obd/accepted-constraints.txt"
    verifier_command = 'python scripts/verify_frozen_environment.py "$ACCEPTED_ENVIRONMENT"'

    assert FROZEN_ENV_VERIFIER.is_file()
    assert "torch==2.13.0+cpu" in accepted
    assert "obp==0.4.1" in accepted
    assert "sb-obp==0.5.10" in accepted
    assert f"ACCEPTED_ENVIRONMENT: {accepted_path}" in workflow
    assert "cache-dependency-path: |\n            pyproject.toml\n" in workflow
    assert accepted_path in workflow
    assert "Install frozen CPU research environment" in workflow
    assert "'torch>=2.2,<3'" not in workflow
    assert "'torch==2.13.0+cpu'" in workflow
    assert "'obp==0.4.1'" in workflow
    assert f"--constraint {constraints_path}" in workflow
    assert verifier_command in workflow
    assert workflow.index(verifier_command) < workflow.index(
        "Run full preregistered Open Bandit benchmark"
    )
    assert constraints_path in workflow.split(
        "Upload full OBD research evidence", maxsplit=1
    )[1]
