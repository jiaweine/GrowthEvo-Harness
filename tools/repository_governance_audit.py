#!/usr/bin/env python3
"""Fail-closed audit for GrowthEvo's GitHub main-branch governance contract.

This script is intentionally read-only. It verifies that an active repository
ruleset protects the default branch with the exact CI evidence gates tracked in
issue #63. It can run against live GitHub API responses or fixture dictionaries
in unit tests.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

API_VERSION = "2022-11-28"
GITHUB_ACTIONS_INTEGRATION_ID = 15368
REQUIRED_CHECKS = (
    "test (3.11)",
    "test (3.12)",
    "test (3.13)",
    "test (3.14)",
    "package",
    "obd-integration",
)


@dataclass(frozen=True)
class GovernanceAuditResult:
    ok: bool
    failures: tuple[str, ...]
    matched_ruleset_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failures": list(self.failures),
            "matched_ruleset_ids": list(self.matched_ruleset_ids),
            "required_checks": list(REQUIRED_CHECKS),
            "github_actions_integration_id": GITHUB_ACTIONS_INTEGRATION_ID,
        }


def _rule_map(ruleset: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for rule in ruleset.get("rules", []):
        if not isinstance(rule, dict):
            continue
        rule_type = rule.get("type")
        if isinstance(rule_type, str):
            out.setdefault(rule_type, []).append(rule)
    return out


def _targets_branch(ruleset: dict[str, Any], branch: str) -> bool:
    if ruleset.get("target") != "branch":
        return False
    conditions = ruleset.get("conditions")
    if not isinstance(conditions, dict):
        return False
    ref_name = conditions.get("ref_name")
    if not isinstance(ref_name, dict):
        return False
    includes = ref_name.get("include", [])
    excludes = ref_name.get("exclude", [])
    if not isinstance(includes, list) or not isinstance(excludes, list):
        return False
    explicit = f"refs/heads/{branch}"
    included = explicit in includes or "~DEFAULT_BRANCH" in includes
    excluded = explicit in excludes or "~DEFAULT_BRANCH" in excludes
    return included and not excluded


def _checks_match(rule: dict[str, Any]) -> bool:
    params = rule.get("parameters")
    if not isinstance(params, dict):
        return False
    if params.get("strict_required_status_checks_policy") is not True:
        return False
    checks = params.get("required_status_checks")
    if not isinstance(checks, list):
        return False
    normalized: set[tuple[str, int]] = set()
    for check in checks:
        if not isinstance(check, dict):
            return False
        context = check.get("context")
        integration_id = check.get("integration_id")
        if not isinstance(context, str) or not isinstance(integration_id, int):
            return False
        normalized.add((context, integration_id))
    expected = {(name, GITHUB_ACTIONS_INTEGRATION_ID) for name in REQUIRED_CHECKS}
    return normalized == expected


def _pull_request_rule_ok(rule: dict[str, Any]) -> bool:
    params = rule.get("parameters")
    return isinstance(params, dict) and params.get("required_approving_review_count") == 0


def _ruleset_satisfies_contract(ruleset: dict[str, Any], branch: str) -> bool:
    if ruleset.get("enforcement") != "active":
        return False
    if not _targets_branch(ruleset, branch):
        return False
    bypass = ruleset.get("bypass_actors", [])
    if bypass not in ([], None):
        return False

    rules = _rule_map(ruleset)
    if not any(_pull_request_rule_ok(rule) for rule in rules.get("pull_request", [])):
        return False
    if not any(_checks_match(rule) for rule in rules.get("required_status_checks", [])):
        return False
    if not rules.get("deletion"):
        return False
    if not rules.get("non_fast_forward"):
        return False
    return True


def audit_governance(
    *,
    branch_data: dict[str, Any],
    rulesets: Iterable[dict[str, Any]],
    branch: str = "main",
) -> GovernanceAuditResult:
    failures: list[str] = []
    if branch_data.get("name") != branch:
        failures.append(f"branch API returned {branch_data.get('name')!r}, expected {branch!r}")

    matched = tuple(
        int(ruleset["id"])
        for ruleset in rulesets
        if isinstance(ruleset, dict)
        and isinstance(ruleset.get("id"), int)
        and _ruleset_satisfies_contract(ruleset, branch)
    )
    if not matched:
        branch_flag = branch_data.get("protected") is True
        failures.append(
            "no active branch ruleset exactly matches the GrowthEvo governance contract "
            "(PR-only, zero approvals, six strict GitHub Actions checks, no bypass, "
            "no deletion, no force-push); "
            f"branch API protected={branch_flag}"
        )

    return GovernanceAuditResult(
        ok=not failures,
        failures=tuple(failures),
        matched_ruleset_ids=matched,
    )


def _request_json(url: str, token: str | None) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "GrowthEvo-Repository-Governance-Audit",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub API request failed for {url}: {exc}") from exc


def fetch_live_state(repo: str, branch: str, token: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = f"https://api.github.com/repos/{repo}"
    branch_data = _request_json(f"{base}/branches/{branch}", token)
    summaries = _request_json(f"{base}/rulesets", token)
    if not isinstance(branch_data, dict):
        raise RuntimeError("unexpected GitHub branch response shape")
    if not isinstance(summaries, list):
        raise RuntimeError("unexpected GitHub rulesets response shape")

    details: list[dict[str, Any]] = []
    for summary in summaries:
        if not isinstance(summary, dict) or not isinstance(summary.get("id"), int):
            continue
        detail = _request_json(f"{base}/rulesets/{summary['id']}", token)
        if isinstance(detail, dict):
            details.append(detail)
    return branch_data, details


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "jiaweine/GrowthEvo-Harness"))
    parser.add_argument("--branch", default="main")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        branch_data, rulesets = fetch_live_state(args.repo, args.branch, token)
        result = audit_governance(branch_data=branch_data, rulesets=rulesets, branch=args.branch)
    except Exception as exc:  # fail closed for API/schema errors
        result = GovernanceAuditResult(
            ok=False,
            failures=(f"audit execution failed: {exc}",),
            matched_ruleset_ids=(),
        )

    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True))
    else:
        print("repository governance audit:", "PASS" if result.ok else "FAIL")
        for failure in result.failures:
            print(f"- {failure}")
        if result.matched_ruleset_ids:
            print("- matched rulesets:", ", ".join(map(str, result.matched_ruleset_ids)))

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
