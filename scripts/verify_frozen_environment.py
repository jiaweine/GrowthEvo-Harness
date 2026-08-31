from __future__ import annotations

import argparse
import re
import sys
from importlib.metadata import PackageNotFoundError, distributions, version
from pathlib import Path
from typing import Callable, Iterable


VersionLookup = Callable[[str], str]
DEFAULT_ALLOWED_EXTRA_DISTRIBUTIONS = frozenset({"pip", "growthevo-harness"})


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_exact_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-e "):
            continue
        if line.count("==") != 1:
            raise ValueError(
                f"{path}:{line_number}: expected an exact 'name==version' pin, got {line!r}"
            )
        name, expected = (part.strip() for part in line.split("==", maxsplit=1))
        if not name or not expected:
            raise ValueError(f"{path}:{line_number}: incomplete exact pin {line!r}")
        if name in pins and pins[name] != expected:
            raise ValueError(
                f"{path}:{line_number}: conflicting pins for {name}: "
                f"{pins[name]!r} vs {expected!r}"
            )
        pins[name] = expected
    if not pins:
        raise ValueError(f"{path}: no exact distribution pins found")
    return pins


def find_mismatches(
    pins: dict[str, str],
    *,
    lookup: VersionLookup = version,
) -> list[str]:
    mismatches: list[str] = []
    for name, expected in sorted(pins.items(), key=lambda item: item[0].lower()):
        try:
            actual = lookup(name)
        except PackageNotFoundError:
            mismatches.append(f"{name}: missing (expected {expected})")
            continue
        if actual != expected:
            mismatches.append(f"{name}: installed {actual}, expected {expected}")
    return mismatches


def installed_distribution_names() -> set[str]:
    names: set[str] = set()
    for distribution in distributions():
        name = distribution.metadata.get("Name")
        if name:
            names.add(_canonical_distribution_name(name))
    return names


def find_unexpected_distributions(
    pins: dict[str, str],
    *,
    installed_names: Iterable[str] | None = None,
    allowed_extra: Iterable[str] = DEFAULT_ALLOWED_EXTRA_DISTRIBUTIONS,
) -> list[str]:
    expected = {_canonical_distribution_name(name) for name in pins}
    allowed = {_canonical_distribution_name(name) for name in allowed_extra}
    if installed_names is None:
        installed = installed_distribution_names()
    else:
        installed = {_canonical_distribution_name(name) for name in installed_names}
    return sorted(installed - expected - allowed)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that every exact distribution pin in a frozen pip environment "
            "snapshot matches the currently installed environment and that no "
            "unexpected external distributions are installed. Editable GrowthEvo "
            "and pip itself are allowed because the repository commit is verified "
            "separately and pip freeze omits pip."
        )
    )
    parser.add_argument("snapshot", type=Path, help="Frozen pip environment snapshot.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    pins = load_exact_pins(args.snapshot)
    mismatches = find_mismatches(pins)
    unexpected = find_unexpected_distributions(pins)
    if mismatches or unexpected:
        print("Frozen environment verification failed:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"- {mismatch}", file=sys.stderr)
        for name in unexpected:
            print(f"- {name}: unexpected installed distribution", file=sys.stderr)
        return 1
    print(
        f"Verified {len(pins)} frozen distribution pins from {args.snapshot}; "
        "no unexpected external distributions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
