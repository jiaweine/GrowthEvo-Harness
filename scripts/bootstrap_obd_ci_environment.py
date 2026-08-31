from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path


CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"
PYPI_INDEX_URL = "https://pypi.org/simple"
TORCH_REQUIREMENT = "torch==2.13.0+cpu"
LEGACY_OBP_REQUIREMENT = "obp==0.4.1"
GROWTHEVO_OBD_REQUIREMENT = ".[obd]"

EXPECTED_TORCH_VERSION = "2.13.0+cpu"
EXPECTED_OBP_MODULE_VERSION = "0.5.5"
EXPECTED_SB_OBP_DISTRIBUTION_VERSION = "0.5.10"
EXPECTED_LEGACY_OBP_DISTRIBUTION_VERSION = "0.4.1"


def _run(command: list[str], *, stdout=None) -> None:
    print("+", shlex.join(command), flush=True)
    subprocess.run(command, check=True, stdout=stdout, text=True)


def _pip(*args: str, stdout=None) -> None:
    _run([sys.executable, "-m", "pip", *args], stdout=stdout)


def install_environment() -> None:
    _pip("install", "--upgrade", "pip")
    _pip(
        "install",
        "--index-url",
        CPU_INDEX_URL,
        "--extra-index-url",
        PYPI_INDEX_URL,
        TORCH_REQUIREMENT,
    )
    _pip("install", "--no-deps", LEGACY_OBP_REQUIREMENT)
    _pip("install", "-e", GROWTHEVO_OBD_REQUIREMENT)


def verify_environment() -> None:
    import obp
    import torch

    cuda_available = torch.cuda.is_available()
    sb_obp_distribution = version("sb-obp")
    legacy_obp_distribution = version("obp")

    assert torch.__version__ == EXPECTED_TORCH_VERSION
    assert not cuda_available
    assert obp.__version__ == EXPECTED_OBP_MODULE_VERSION
    assert sb_obp_distribution == EXPECTED_SB_OBP_DISTRIBUTION_VERSION
    assert legacy_obp_distribution == EXPECTED_LEGACY_OBP_DISTRIBUTION_VERSION

    print(
        "torch", torch.__version__,
        "cuda_available=", cuda_available,
        "obp_module_version=", obp.__version__,
        "sb_obp_distribution=", sb_obp_distribution,
        "legacy_obp_distribution=", legacy_obp_distribution,
    )


def freeze_environment(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        _pip("freeze", stdout=handle)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install and verify the CPU-only dependency environment shared by the "
            "small-OBD integration job and the trusted default-branch cache seeder."
        )
    )
    parser.add_argument(
        "--freeze-output",
        type=Path,
        help="Optionally persist the resolved pip environment to this path.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    install_environment()
    verify_environment()
    if args.freeze_output is not None:
        freeze_environment(args.freeze_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
