from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import (
    evaluate_randomized_targeting,
    kuairand_reward,
    load_criteo_uplift,
    load_kuairand,
    load_open_bandit,
    open_bandit_to_ope,
)
from growthevo.models import Channel
from growthevo.rl.ope import evaluate_policy


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _criteo_header() -> str:
    return ",".join([*(f"f{i}" for i in range(12)), "treatment", "conversion", "visit", "exposure"])


def _criteo_row(offset: float, treatment: int, visit: int, exposure: int) -> str:
    features = [str(offset + index / 100.0) for index in range(12)]
    return ",".join([*features, str(treatment), "0", str(visit), str(exposure)])


def test_criteo_loader_uses_random_assignment_not_post_treatment_exposure(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "criteo.csv",
        "\n".join(
            [
                _criteo_header(),
                _criteo_row(0.0, 1, 1, 0),
                _criteo_row(1.0, 0, 0, 1),
                _criteo_row(2.0, 1, 1, 1),
                _criteo_row(3.0, 0, 0, 0),
            ]
        ),
    )

    data = load_criteo_uplift(path, outcome="visit", treatment_propensity=0.5)
    assert data.records[0].action is Channel.ADS
    assert data.records[1].action is Channel.NO_TREATMENT

    result = evaluate_randomized_targeting(
        data.records,
        [4.0, 3.0, 2.0, 1.0],
        selected_fraction=0.5,
    )
    assert result.sample_size == 4
    assert result.incremental_value_vs_none == pytest.approx(0.5)


def test_open_bandit_adapter_preserves_logged_propensity_for_current_ope(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "bandit.csv",
        "\n".join(
            [
                "timestamp,item_id,position,click,propensity_score,user_feature_0,user-item_affinity_0",
                "2020-01-01 00:00:00,7,1,1,0.25,segment-A,0.8",
                "2020-01-01 00:00:01,3,2,0,0.50,segment-B,0.1",
            ]
        ),
    )

    rows = load_open_bandit(path)
    ope_rows = open_bandit_to_ope(
        rows,
        target_action_probability=lambda row: 0.5 if row.item_id == 7 else 0.25,
        baseline_q=lambda row: 0.1,
        target_q=lambda row: 0.2,
        cluster_key=lambda row: f"item-block-{row.item_id}",
        record_identity=lambda row: f"{row.timestamp}:{row.item_id}:{row.position}",
    )
    estimate = evaluate_policy(ope_rows)

    assert rows[0].propensity_score == pytest.approx(0.25)
    assert rows[0].categorical_context == ("segment-A",)
    assert ope_rows[0].behavior_propensity == pytest.approx(0.25)
    assert ope_rows[0].importance_weight == pytest.approx(2.0)
    assert ope_rows[0].record_id == "2020-01-01 00:00:00:7:1"
    assert ope_rows[0].cluster_id == "item-block-7"
    assert estimate.ips == pytest.approx(1.0)
    assert estimate.sample_size == 2
    assert estimate.standard_error_method == "cluster"
    assert estimate.cluster_count == 2


def test_kuairand_loader_keeps_randomization_as_provenance_and_reward_is_explicit(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "kuairand.csv",
        "\n".join(
            [
                "user_id,video_id,time_ms,date,hourmin,tab,is_rand,is_click,is_like,is_follow,is_comment,is_forward,is_hate,long_view,play_time_ms,duration_ms",
                "1,10,1000,20220422,900,1,1,1,0,0,0,0,0,1,8000,9000",
            ]
        ),
    )

    row = load_kuairand(path)[0]

    assert row.is_random is True
    assert kuairand_reward(row, weights={"is_click": 1.0, "is_hate": -1.0}) == pytest.approx(1.0)
