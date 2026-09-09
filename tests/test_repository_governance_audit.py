from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "repository_governance_audit.py"
SPEC = importlib.util.spec_from_file_location("repository_governance_audit", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
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
                "parameters": {"required_approving_review_count": 0},
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


def test_good_ruleset_passes() -> None:
    result = MODULE.audit_governance(
        branch_data={"name": "main", "protected": True},
        rulesets=[_good_ruleset()],
    )
    assert result.ok is True
    assert result.failures == ()
    assert result.matched_ruleset_ids == (123,)


def test_unprotected_branch_fails_even_with_good_ruleset() -> None:
    result = MODULE.audit_governance(
        branch_data={"name": "main", "protected": False},
        rulesets=[_good_ruleset()],
    )
    assert result.ok is False
    assert any("not reported as protected" in failure for failure in result.failures)


def test_missing_check_fails_closed() -> None:
    ruleset = _good_ruleset()
    status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    status_rule["parameters"]["required_status_checks"] = status_rule["parameters"]["required_status_checks"][:-1]
    result = MODULE.audit_governance(
        branch_data={"name": "main", "protected": True},
        rulesets=[ruleset],
    )
    assert result.ok is False


def test_extra_manual_full_data_check_is_not_accepted() -> None:
    ruleset = _good_ruleset()
    status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    status_rule["parameters"]["required_status_checks"].append(
        {
            "context": "full-obd-production-evidence",
            "integration_id": MODULE.GITHUB_ACTIONS_INTEGRATION_ID,
        }
    )
    result = MODULE.audit_governance(
        branch_data={"name": "main", "protected": True},
        rulesets=[ruleset],
    )
    assert result.ok is False


def test_wrong_actions_integration_id_fails() -> None:
    ruleset = _good_ruleset()
    status_rule = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
    status_rule["parameters"]["required_status_checks"][0]["integration_id"] = 999
    result = MODULE.audit_governance(
        branch_data={"name": "main", "protected": True},
        rulesets=[ruleset],
    )
    assert result.ok is False


def test_bypass_actor_fails() -> None:
    ruleset = _good_ruleset()
    ruleset["bypass_actors"] = [{"actor_id": 1, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
    result = MODULE.audit_governance(
        branch_data={"name": "main", "protected": True},
        rulesets=[ruleset],
    )
    assert result.ok is False


def test_inactive_or_wrong_branch_rulesets_fail() -> None:
    inactive = _good_ruleset()
    inactive["enforcement"] = "evaluate"
    wrong_branch = _good_ruleset()
    wrong_branch["id"] = 124
    wrong_branch["conditions"]["ref_name"]["include"] = ["refs/heads/release"]
    result = MODULE.audit_governance(
        branch_data={"name": "main", "protected": True},
        rulesets=[inactive, wrong_branch],
    )
    assert result.ok is False
