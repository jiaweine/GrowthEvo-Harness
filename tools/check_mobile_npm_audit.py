#!/usr/bin/env python3
"""Fail closed when npm audit exceeds GrowthEvo's reviewed mobile baseline."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


GHSA_RE = re.compile(r"/(GHSA-[A-Za-z0-9-]+)$")
SEVERITY_RANK = {"info": 0, "low": 1, "moderate": 2, "high": 3, "critical": 4}


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _root_advisories(report: dict[str, Any]) -> dict[str, dict[str, str]]:
    vulnerabilities = report.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        raise ValueError("npm audit report is missing a vulnerabilities object")

    roots: dict[str, dict[str, str]] = {}
    for package, vuln in vulnerabilities.items():
        if not isinstance(package, str) or not isinstance(vuln, dict):
            raise ValueError("npm audit vulnerabilities contains an invalid entry")
        via = vuln.get("via")
        if not isinstance(via, list):
            raise ValueError(f"{package}: npm audit entry is missing via[]")
        for item in via:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            severity = item.get("severity")
            if not isinstance(url, str) or not isinstance(severity, str):
                raise ValueError(f"{package}: advisory entry is missing url/severity")
            match = GHSA_RE.search(url)
            if not match:
                raise ValueError(f"{package}: unrecognized advisory URL {url!r}")
            ghsa = match.group(1)
            previous = roots.get(ghsa)
            candidate = {"package": package, "severity": severity}
            if previous is not None and previous != candidate:
                raise ValueError(
                    f"{ghsa}: conflicting root advisory identities "
                    f"{previous!r} vs {candidate!r}"
                )
            roots[ghsa] = candidate
    return roots


def audit(
    report: dict[str, Any], baseline: dict[str, Any]
) -> tuple[bool, list[str], dict[str, Any]]:
    failures: list[str] = []

    metadata = report.get("metadata")
    counts = metadata.get("vulnerabilities") if isinstance(metadata, dict) else None
    if not isinstance(counts, dict):
        raise ValueError("npm audit report is missing metadata.vulnerabilities")

    limits = baseline.get("max_vulnerability_counts")
    if not isinstance(limits, dict):
        raise ValueError("baseline is missing max_vulnerability_counts")
    for key in ("critical", "high", "moderate", "low", "info", "total"):
        actual = counts.get(key)
        limit = limits.get(key)
        if type(actual) is not int or type(limit) is not int:
            raise ValueError(f"invalid vulnerability count for {key}")
        if actual > limit:
            failures.append(f"{key} vulnerabilities increased: {actual} > reviewed {limit}")

    allowed_roots = baseline.get("allowed_root_advisories")
    if not isinstance(allowed_roots, dict):
        raise ValueError("baseline is missing allowed_root_advisories")
    roots = _root_advisories(report)

    for ghsa, observed in sorted(roots.items()):
        allowed = allowed_roots.get(ghsa)
        if not isinstance(allowed, dict):
            failures.append(
                f"unreviewed root advisory appeared: {ghsa} ({observed['package']})"
            )
            continue
        if observed["package"] != allowed.get("package"):
            failures.append(
                f"{ghsa} moved from reviewed package {allowed.get('package')!r} "
                f"to {observed['package']!r}"
            )
        observed_rank = SEVERITY_RANK.get(observed["severity"])
        allowed_rank = SEVERITY_RANK.get(allowed.get("severity"))
        if observed_rank is None or allowed_rank is None:
            raise ValueError(f"{ghsa}: unknown severity")
        if observed_rank > allowed_rank:
            failures.append(
                f"{ghsa} severity increased: {observed['severity']} > "
                f"{allowed.get('severity')}"
            )

    vulnerabilities = report.get("vulnerabilities")
    current_packages = set(vulnerabilities) if isinstance(vulnerabilities, dict) else set()
    allowed_packages_raw = baseline.get("allowed_affected_packages")
    if not isinstance(allowed_packages_raw, list) or not all(
        isinstance(item, str) for item in allowed_packages_raw
    ):
        raise ValueError("baseline is missing allowed_affected_packages")
    unexpected_packages = current_packages - set(allowed_packages_raw)
    if unexpected_packages:
        failures.append(
            "new affected packages appeared: " + ", ".join(sorted(unexpected_packages))
        )

    summary = {
        "ok": not failures,
        "counts": {
            key: counts[key]
            for key in ("critical", "high", "moderate", "low", "info", "total")
        },
        "root_advisories": roots,
        "affected_packages": sorted(current_packages),
        "failures": failures,
    }
    return not failures, failures, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()

    try:
        report = _load(args.report)
        baseline = _load(args.baseline)
        ok, _failures, summary = audit(report, baseline)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
