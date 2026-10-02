#!/usr/bin/env python3
"""Fail-closed audit for GrowthEvo's GitHub main-branch governance contract.

This script is intentionally read-only. It verifies that an active repository
ruleset protects the default branch with the exact CI evidence gates tracked in
issue #63. It can run against live GitHub API responses or fixture dictionaries
in unit tests.
"""

from __future__ import annotations

import argparse
import fnmatch
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
REQUIRED_RULE_TYPES = (
    "pull_request",
    "required_status_checks",
    "deletion",
    "non_fast_forward",
)
REQUIRED_MERGE_METHODS = frozenset({"merge", "squash", "rebase"})


@dataclass(frozen=True)
class GovernanceAuditResult:
    ok: bool
    pending: bool
    failures: tuple[str, ...]
    matched_ruleset_ids: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "pending": self.pending,
            "failures": list(self.failures),
            "matched_ruleset_ids": list(self.matched_ruleset_ids),
            "required_checks": list(REQUIRED_CHECKS),
            "github_actions_integration_id": GITHUB_ACTIONS_INTEGRATION_ID,
        }


def _rule_map(ruleset: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    rules = ruleset.get("rules")
    if not isinstance(rules, list):
        return out
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rule_type = rule.get("type")
        if isinstance(rule_type, str):
            out.setdefault(rule_type, []).append(rule)
    return out


def _ref_pattern_matches(pattern: str, branch: str) -> bool:
    explicit = f"refs/heads/{branch}"
    if pattern in {"~DEFAULT_BRANCH", "~ALL", explicit}:
        return True
    if pattern.startswith("refs/heads/"):
        return fnmatch.fnmatchcase(explicit, pattern)
    return False


def _targets_branch(ruleset: dict[str, Any], branch: str) -> bool:
    """Return whether a valid ruleset condition applies to the audited branch."""
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
    if not all(isinstance(item, str) for item in includes + excludes):
        return False
    included = any(_ref_pattern_matches(item, branch) for item in includes)
    excluded = any(_ref_pattern_matches(item, branch) for item in excludes)
    return included and not excluded


def _targets_only_branch(ruleset: dict[str, Any], branch: str) -> bool:
    """Require the contract ruleset to target only main/default, not extra refs."""
    if ruleset.get("target") != "branch":
        return False
    conditions = ruleset.get("conditions")
    if not isinstance(conditions, dict):
        return False
    ref_name = conditions.get("ref_name")
    if not isinstance(ref_name, dict):
        return False
    includes = ref_name.get("include")
    excludes = ref_name.get("exclude")
    if not isinstance(includes, list) or not isinstance(excludes, list):
        return False
    explicit = f"refs/heads/{branch}"
    return len(includes) == 1 and includes[0] in {explicit, "~DEFAULT_BRANCH"} and excludes == []


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
    if len(normalized) != len(checks):
        return False
    expected = {(name, GITHUB_ACTIONS_INTEGRATION_ID) for name in REQUIRED_CHECKS}
    return normalized == expected


def _pull_request_rule_ok(rule: dict[str, Any]) -> bool:
    params = rule.get("parameters")
    if not isinstance(params, dict):
        return False

    methods = params.get("allowed_merge_methods")
    if not isinstance(methods, list) or len(methods) != len(REQUIRED_MERGE_METHODS):
        return False
    if not all(isinstance(method, str) for method in methods):
        return False
    if frozenset(methods) != REQUIRED_MERGE_METHODS:
        return False

    approving_count = params.get("required_approving_review_count")
    if type(approving_count) is not int or approving_count != 0:
        return False

    return (
        params.get("dismiss_stale_reviews_on_push") is False
        and params.get("require_code_owner_review") is False
        and params.get("require_last_push_approval") is False
        and params.get("required_review_thread_resolution") is False
    )


def _ruleset_satisfies_contract(ruleset: dict[str, Any], branch: str) -> bool:
    if not isinstance(ruleset.get("id"), int):
        return False
    if ruleset.get("enforcement") != "active":
        return False
    if not _targets_only_branch(ruleset, branch):
        return False
    if ruleset.get("bypass_actors") != []:
        return False

    rules = _rule_map(ruleset)
    if set(rules) != set(REQUIRED_RULE_TYPES):
        return False
    if any(len(rules[rule_type]) != 1 for rule_type in REQUIRED_RULE_TYPES):
        return False
    if not _pull_request_rule_ok(rules["pull_request"][0]):
        return False
    if not _checks_match(rules["required_status_checks"][0]):
        return False
    return True


def audit_governance(
    *,
    branch_data: dict[str, Any],
    rulesets: Iterable[dict[str, Any]],
    branch: str = "main",
    allow_unconfigured: bool = False,
) -> GovernanceAuditResult:
    failures: list[str] = []
    if branch_data.get("name") != branch:
        failures.append(f"branch API returned {branch_data.get('name')!r}, expected {branch!r}")

    ruleset_list = tuple(rulesets)
    active_targeting_rulesets = tuple(
        ruleset
        for ruleset in ruleset_list
        if isinstance(ruleset, dict)
        and ruleset.get("enforcement") == "active"
        and _targets_branch(ruleset, branch)
    )
    matched_rulesets = tuple(
        ruleset
        for ruleset in active_targeting_rulesets
        if _ruleset_satisfies_contract(ruleset, branch)
    )
    matched = tuple(int(ruleset["id"]) for ruleset in matched_rulesets)

    pending = False
    if allow_unconfigured and not active_targeting_rulesets:
        pending = True
    elif len(active_targeting_rulesets) != 1 or len(matched_rulesets) != 1:
        branch_flag = branch_data.get("protected") is True
        active_ids = [ruleset.get("id") for ruleset in active_targeting_rulesets]
        failures.append(
            "expected exactly one active branch ruleset targeting main and exactly matching "
            "the GrowthEvo governance contract (PR-only; zero approvals; no code-owner or "
            "last-push approval; merge/squash/rebase allowed; six strict GitHub Actions checks; "
            "no bypass actors; block deletion and non-fast-forward updates); "
            f"active targeting rulesets={active_ids!r}, matched={list(matched)!r}, "
            f"branch API protected={branch_flag}"
        )

    return GovernanceAuditResult(
        ok=not failures,
        pending=pending and not failures,
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
    parser.add_argument(
        "--allow-unconfigured-while-issue-open",
        type=int,
        metavar="ISSUE",
        help=(
            "treat a completely unconfigured repository as pending only while the "
            "specified governance tracker issue remains open"
        ),
    )
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    try:
        branch_data, rulesets = fetch_live_state(args.repo, args.branch, token)
        allow_unconfigured = False
        if args.allow_unconfigured_while_issue_open is not None:
            issue_number = args.allow_unconfigured_while_issue_open
            issue_data = _request_json(
                f"https://api.github.com/repos/{args.repo}/issues/{issue_number}",
                token,
            )
            if not isinstance(issue_data, dict) or issue_data.get("state") not in {"open", "closed"}:
                raise RuntimeError("unexpected GitHub issue response shape")
            allow_unconfigured = issue_data["state"] == "open"
        result = audit_governance(
            branch_data=branch_data,
            rulesets=rulesets,
            branch=args.branch,
            allow_unconfigured=allow_unconfigured,
        )
    except Exception as exc:  # fail closed for API/schema errors
        result = GovernanceAuditResult(
            ok=False,
            pending=False,
            failures=(f"audit execution failed: {exc}",),
            matched_ruleset_ids=(),
        )

    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True))
    else:
        status = "PENDING" if result.pending else ("PASS" if result.ok else "FAIL")
        print("repository governance audit:", status)
        for failure in result.failures:
            print(f"- {failure}")
        if result.pending:
            print("- governance tracker remains open and no active target ruleset exists yet")
        if result.matched_ruleset_ids:
            print("- matched rulesets:", ", ".join(map(str, result.matched_ruleset_ids)))

    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
