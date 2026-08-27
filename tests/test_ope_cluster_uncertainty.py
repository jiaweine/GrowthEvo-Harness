from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import load_open_bandit, open_bandit_to_ope
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


def _records(clustered: bool) -> list[LoggedBanditRecord]:
    rewards = (1.0, 1.0, 0.0, 0.0)
    clusters = ("left", "left", "right", "right")
    return [
        LoggedBanditRecord(
            reward=reward,
            behavior_propensity=0.5,
            target_action_probability=0.5,
            baseline_q=0.5,
            target_q=0.5,
            cluster_id=clusters[index] if clustered else None,
        )
        for index, reward in enumerate(rewards)
    ]


def test_cluster_robust_ope_reflects_within_cluster_dependence() -> None:
    iid = evaluate_policy(_records(clustered=False))
    clustered = evaluate_policy(_records(clustered=True))

    assert iid.ips == pytest.approx(clustered.ips)
    assert iid.standard_error_method == "iid"
    assert clustered.standard_error_method == "cluster"
    assert clustered.cluster_count == 2
    assert clustered.ips_standard_error > iid.ips_standard_error


def test_ope_rejects_partial_cluster_annotation() -> None:
    rows = _records(clustered=True)
    rows[0] = LoggedBanditRecord(
        reward=rows[0].reward,
        behavior_propensity=rows[0].behavior_propensity,
        target_action_probability=rows[0].target_action_probability,
        baseline_q=rows[0].baseline_q,
        target_q=rows[0].target_q,
    )

    with pytest.raises(ValueError, match="every record or none"):
        evaluate_policy(rows)


def test_open_bandit_adapter_accepts_protocol_defined_cluster_key(tmp_path: Path) -> None:
    path = tmp_path / "bandit.csv"
    path.write_text(
        "\n".join(
            [
                "timestamp,item_id,position,click,propensity_score,user_feature_0,user-item_affinity_0",
                "2020-01-01 00:00:00,7,1,1,0.5,A,0.8",
                "2020-01-02 00:00:00,3,1,0,0.5,B,0.1",
            ]
        ),
        encoding="utf-8",
    )
    rows = load_open_bandit(path)

    records = open_bandit_to_ope(
        rows,
        target_action_probability=lambda row: row.propensity_score,
        baseline_q=lambda row: 0.5,
        target_q=lambda row: 0.5,
        cluster_key=lambda row: row.timestamp.split(" ", 1)[0],
    )

    assert records[0].cluster_id == "2020-01-01"
    assert records[1].cluster_id == "2020-01-02"
    estimate = evaluate_policy(records)
    assert estimate.standard_error_method == "cluster"
    assert estimate.cluster_count == 2
