from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
from typing import Any


THREAD_ENVIRONMENT = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _command_output(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def capture_numeric_runtime() -> dict[str, Any]:
    import numpy as np
    import scipy
    import sklearn
    from sklearn.linear_model import LogisticRegression  # noqa: F401
    from threadpoolctl import threadpool_info

    # Exercise NumPy's numeric backend before inspecting loaded thread pools.
    probe = np.arange(64, dtype=float).reshape(8, 8)
    _ = probe @ probe.T

    numpy_config = StringIO()
    with redirect_stdout(numpy_config):
        np.show_config()

    libc_name, libc_version = platform.libc_ver()
    return {
        "schema_version": "growthevo.numeric-runtime.v1",
        "runner": {
            "runner_os": os.environ.get("RUNNER_OS"),
            "runner_arch": os.environ.get("RUNNER_ARCH"),
            "image_os": os.environ.get("ImageOS"),
            "image_version": os.environ.get("ImageVersion"),
        },
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "libc_name": libc_name,
            "libc_version": libc_version,
        },
        "packages": {
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "thread_environment": {
            name: os.environ.get(name) for name in THREAD_ENVIRONMENT
        },
        "threadpool_info": threadpool_info(),
        "numpy_config": numpy_config.getvalue(),
        "lscpu": _command_output(["lscpu", "--json"]),
        "os_release": _command_output(["cat", "/etc/os-release"]),
        "uname": _command_output(["uname", "-a"]),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture hosted-runner CPU, BLAS/threadpool, Python, and OS metadata "
            "needed to diagnose cross-host floating-point variation."
        )
    )
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = capture_numeric_runtime()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
