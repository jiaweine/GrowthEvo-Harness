from __future__ import annotations

from copy import deepcopy
import importlib.util
import re
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "repository_governance_audit.py"
SPEC = importlib.util.spec_from_file_location("repository_governance_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _good_ruleset() -> dict:
    return {
        "id": 123,
        "name": "Protect main with GrowthEvo evidence gates",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {
            "ref_name": {
                "include": ["~DEFAULT_BRANCH"],
                "exclude": [],
            }
        },
        "rules": [
            {
                "type": "pull_request",
                "parameters": {
                    "allowed_merge_methods": ["merge", "squash", "rebase"],
                    "dismiss_stale_reviews_on_push": False,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_approving_review_count": 0,
                    "required_review_thread_resolution": False,
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": [
                        {
                            "context": context,
                            "integration_id": MODULE.GITHUB_ACTIONS_INTEGRATION_ID,
                        }
                        for context in MODULE.REQUIRED_CHECKS
                    ],
                },
            },
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ],
    }


def _audit(rulesets: list[dict], *, protected: bool = True, allow_unconfigured: bool = False):
    return MODULE.audit_governance(
        branch_data={"name": "main", "protected": protected},
        rulesets=rulesets,
        allow_unconfigured=allow_unconfigured,
    )


def test_good_ruleset_passes() -> None:
    result = _audit([_good_ruleset()])
    assert result.ok is True
    assert result.pending is False
    assert result.failures == ()
    assert result.matched_ruleset_ids == (123,)


def test_effective_ruleset_is_sufficient_even_if_branch_flag_is_false() -> None:
    result = _audit([_good_ruleset()], protected=False)
    assert result.ok is True
    assert result.failures == ()


def test_missing_ruleset_fails_even_if_branch_flag_is_true() -> None:
    result = _audit([])
    assert result.ok is False
    assert any("expected exactly one active branch ruleset" in failure for failure in result.failures)


def test_open_tracker_can_tolerate_completely_unconfigured_repository() -> None:
    result = _audit([], protected=False, allow_unconfigured=True)
    assert result.ok is True
    assert result.pending is True
    assert result.failures == ()
    assert result.matched_ruleset_ids == ()


def test_bootstrap_mode_rejects_partial_active_ruleset() -> None:
    ruleset = _good_ruleset()
    ruleset["rules"] = [rule for rule in ruleset["rules"] if rule["type"] != "non_fast_forward"]
    result = _audit([ruleset], protected=False, allow_unconfigured=True)
    assert result.ok is False
    assert result.pending is False


def test_missing_check_fails_closed() -> None:
    ruleset = _good_ruleset()
    status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    status_rule["parameters"]["required_status_checks"] = status_rule["parameters"]["required_status_checks"][:-1]
    assert _audit([ruleset]).ok is False


def test_extra_manual_full_data_check_is_not_accepted() -> None:
    ruleset = _good_ruleset()
    status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    status_rule["parameters"]["required_status_checks"].append(
        {
            "context": "full-obd-production-evidence",
            "integration_id": MODULE.GITHUB_ACTIONS_INTEGRATION_ID,
        }
    )
    assert _audit([ruleset]).ok is False


def test_duplicate_required_check_fails() -> None:
    ruleset = _good_ruleset()
    status_rule = next(
        rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks"
    )
    status_rule["parameters"]["required_status_checks"].append(
        dict(status_rule["parameters"]["required_status_checks"][0])
    )
    assert _audit([ruleset]).ok is False


def test_wrong_actions_integration_id_fails() -> None:
    ruleset = _good_ruleset()
    status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    status_rule["parameters"]["required_status_checks"][0]["integration_id"] = 999
    assert _audit([ruleset]).ok is False


def test_bypass_actor_fails() -> None:
    ruleset = _good_ruleset()
    ruleset["bypass_actors"] = [
        {"actor_id": 1, "actor_type": "RepositoryRole", "bypass_mode": "always"}
    ]
    assert _audit([ruleset]).ok is False


def test_missing_bypass_actor_field_fails_closed() -> None:
    ruleset = _good_ruleset()
    del ruleset["bypass_actors"]
    assert _audit([ruleset]).ok is False


def test_inactive_or_wrong_branch_rulesets_fail() -> None:
    inactive = _good_ruleset()
    inactive["enforcement"] = "evaluate"
    wrong_branch = _good_ruleset()
    wrong_branch["id"] = 124
    wrong_branch["conditions"]["ref_name"]["include"] = ["refs/heads/release"]
    assert _audit([inactive, wrong_branch]).ok is False


def test_pull_request_rule_requires_exact_solo_maintainer_contract() -> None:
    mutations = (
        ("allowed_merge_methods", ["squash", "rebase"]),
        ("dismiss_stale_reviews_on_push", True),
        ("require_code_owner_review", True),
        ("require_last_push_approval", True),
        ("required_approving_review_count", 1),
        ("required_approving_review_count", False),
        ("required_review_thread_resolution", True),
    )
    for key, value in mutations:
        ruleset = deepcopy(_good_ruleset())
        pull_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")
        pull_rule["parameters"][key] = value
        assert _audit([ruleset]).ok is False, key


def test_missing_pull_request_parameter_fails_closed() -> None:
    for key in (
        "allowed_merge_methods",
        "dismiss_stale_reviews_on_push",
        "require_code_owner_review",
        "require_last_push_approval",
        "required_approving_review_count",
        "required_review_thread_resolution",
    ):
        ruleset = deepcopy(_good_ruleset())
        pull_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")
        del pull_rule["parameters"][key]
        assert _audit([ruleset]).ok is False, key


def test_extra_rule_type_or_duplicate_contract_rule_fails() -> None:
    extra = _good_ruleset()
    extra["rules"].append({"type": "required_signatures"})
    assert _audit([extra]).ok is False

    duplicate = _good_ruleset()
    duplicate["rules"].append(deepcopy(duplicate["rules"][0]))
    assert _audit([duplicate]).ok is False


def test_ruleset_must_target_only_main_or_default_branch() -> None:
    ruleset = _good_ruleset()
    ruleset["conditions"]["ref_name"]["include"].append("refs/heads/release")
    result = _audit([ruleset], protected=False, allow_unconfigured=True)
    assert result.ok is False
    assert result.pending is False


def test_second_active_main_ruleset_fails_even_if_both_individually_match() -> None:
    first = _good_ruleset()
    second = deepcopy(first)
    second["id"] = 124
    result = _audit([first, second])
    assert result.ok is False
    assert result.pending is False
    assert set(result.matched_ruleset_ids) == {123, 124}


def test_broad_active_main_ruleset_disables_bootstrap_pending() -> None:
    ruleset = _good_ruleset()
    ruleset["conditions"]["ref_name"]["include"] = ["refs/heads/*"]
    result = _audit([ruleset], protected=False, allow_unconfigured=True)
    assert result.ok is False
    assert result.pending is False


def test_required_checks_track_ci_matrix_and_documented_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    matrix = re.search(r'python-version:\s*\[([^\]]+)\]', ci)
    assert matrix is not None
    versions = tuple(re.findall(r'"(\d+\.\d+)"', matrix.group(1)))
    assert versions

    expected = tuple(f"test ({version})" for version in versions) + (
        "package",
        "obd-integration",
    )
    assert MODULE.REQUIRED_CHECKS == expected

    governance_doc = (root / "docs" / "repository_governance_audit.md").read_text(
        encoding="utf-8"
    )
    for check in expected:
        assert f"`{check}`" in governance_doc


def test_governance_workflow_keeps_schedule_bootstrap_and_manual_strict() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (
        root / ".github" / "workflows" / "repository-governance-audit.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "issues: read" in workflow

    conditional = re.search(
        r'if \[\[ "\$\{GITHUB_EVENT_NAME\}" == "schedule" \]\]; then'
        r"(?P<scheduled>.*?)"
        r"\n\s*else"
        r"(?P<manual>.*?)"
        r"\n\s*fi",
        workflow,
        flags=re.DOTALL,
    )
    assert conditional is not None

    scheduled = conditional.group("scheduled")
    manual = conditional.group("manual")
    bootstrap_flag = "--allow-unconfigured-while-issue-open 63"

    assert bootstrap_flag in scheduled
    assert bootstrap_flag not in manual
    assert workflow.count(bootstrap_flag) == 1
    assert "--branch main" in scheduled
    assert "--branch main" in manual
