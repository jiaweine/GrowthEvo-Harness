from __future__ import annotations

import json
from pathlib import Path

from growthevo.operator_cli import main


def _manifest() -> dict:
    return {
        "schema_version": "growthevo.production-operator-manifest.v1",
        "benchmark": "operator-cli-test",
        "dataset": "synthetic-semantic-cases",
        "dataset_source": "test:synthetic",
        "evidence_producer": {"name": "test-evidence", "version": "v1"},
        "candidates": [
            {
                "name": "openai-shadow",
                "endpoint": {
                    "provider": "openai",
                    "model": "pinned-test-model",
                    "reasoning_effort": "medium",
                    "store": False,
                },
                "planner_config": {"shadow_mode": True},
            }
        ],
    }


def _contexts() -> dict:
    return {
        "schema_version": "growthevo.operator-contexts.v1",
        "cases": [
            {
                "case_id": "case-1",
                "belief": {
                    "user_id": "private-user-123",
                    "natural_conversion": 0.1,
                    "channel_uplift": {"email": 0.03},
                    "uplift_uncertainty": 0.1,
                    "ltv": 100.0,
                    "fatigue": 0.1,
                    "churn_risk": 0.35,
                    "touches_24h": 0,
                    "touches_7d": 1,
                    "spend_to_date": 0.0,
                    "days_since_last_active": 1,
                    "lifecycle_stage": "active",
                    "consented_channels": ["email"],
                },
                "goal": {
                    "metric": "incremental_ltv",
                    "horizon_days": 30,
                    "target_delta": 0.05,
                    "constraints": {"max_budget": 10.0},
                },
                "baseline_option": "retain",
            }
        ],
    }


def test_validate_cli_preregisters_without_provider_sdk(
    tmp_path: Path,
    capsys,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_manifest()), encoding="utf-8")

    assert main(["validate", "--manifest", str(manifest)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["manifest_fingerprint"]
    assert output["llm_plan_fingerprint"]
    assert output["candidates"][0]["contract_fingerprint"]


def test_context_fingerprint_cli_does_not_emit_user_id(
    tmp_path: Path,
    capsys,
) -> None:
    contexts = tmp_path / "contexts.json"
    output_path = tmp_path / "fingerprints.json"
    contexts.write_text(json.dumps(_contexts()), encoding="utf-8")

    assert (
        main(
            [
                "context-fingerprints",
                "--contexts",
                str(contexts),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    stdout = capsys.readouterr().out
    assert "private-user-123" not in stdout
    assert "private-user-123" not in output_path.read_text(encoding="utf-8")
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["cases"][0]["case_id"] == "case-1"
    assert len(payload["cases"][0]["context_fingerprint"]) == 40
