from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path
import subprocess
from typing import Iterable


_COMMON = (
    "tools/ci_changed_paths.py",
    "tests/test_ci_changed_paths.py",
)

PROFILES: dict[str, tuple[str, ...]] = {
    "product-auth": _COMMON
    + (
        "growthevo/web/**",
        "constraints/web-container-py313.txt",
        "tests/test_product_oidc_auth.py",
        "tests/test_product_configuration.py",
        "tests/test_product_container_runtime_install.py",
        "scripts/generate_auth_ci_fixture.py",
        "pyproject.toml",
        "Dockerfile",
        "docs/authentication.md",
        ".github/workflows/product-auth.yml",
    ),
    "product-persistence": _COMMON
    + (
        "growthevo/web/**",
        "constraints/web-container-py313.txt",
        "tests/test_product_postgres_persistence.py",
        "scripts/stress_product.py",
        "pyproject.toml",
        "Dockerfile",
        "docs/durable_persistence.md",
        ".github/workflows/product-persistence.yml",
    ),
    "product-stress": _COMMON
    + (
        "growthevo/web/**",
        "scripts/stress_product.py",
        "scripts/stress_decision_semantics.py",
        "constraints/web-container-py313.txt",
        "tests/test_product_*.py",
        "pyproject.toml",
        ".github/workflows/product-stress.yml",
        "Dockerfile",
        ".dockerignore",
    ),
    "product-surface": _COMMON
    + (
        "growthevo/web/**",
        "apps/mobile/**",
        "scripts/build_pages.py",
        "scripts/stress_product.py",
        "scripts/stress_decision_semantics.py",
        "constraints/web-container-py313.txt",
        "tests/test_web_dashboard.py",
        "tests/test_product_*.py",
        "pyproject.toml",
        "Dockerfile",
        ".dockerignore",
        "docs/product_surface.md",
        "docs/deployment_architecture.md",
        "docs/performance_testing.md",
        ".github/workflows/product-surface.yml",
        ".github/workflows/deploy-pages.yml",
    ),
    "codeql": _COMMON
    + (
        "growthevo/**",
        "apps/mobile/**",
        "scripts/**",
        "pyproject.toml",
        ".github/workflows/codeql.yml",
    ),
}


def matches_profile(profile: str, paths: Iterable[str]) -> bool:
    patterns = PROFILES[profile]
    return any(
        fnmatch.fnmatchcase(path, pattern)
        for path in paths
        for pattern in patterns
    )


def changed_paths(*, base: str, head: str, root: Path = Path(".")) -> tuple[str, ...]:
    if not base or not head:
        raise ValueError("both base and head commit SHAs are required")
    if set(base) == {"0"}:
        raise ValueError("an all-zero base SHA cannot define a safe diff")

    completed = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", base, head, "--"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Return whether a stable required CI gate needs its heavy validation steps."
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    paths = changed_paths(base=args.base, head=args.head, root=Path(args.root))
    print("true" if matches_profile(args.profile, paths) else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
