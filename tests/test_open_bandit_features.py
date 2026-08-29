from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import load_open_bandit_item_context


def test_open_bandit_item_context_preserves_raw_anonymized_features(tmp_path: Path) -> None:
    path = tmp_path / "item_context.csv"
    path.write_text(
        "\n".join(
            [
                "item_id,item_feature_0,item_feature_1,item_feature_2,item_feature_3",
                "7,0.25,hash-A,3,hash-Z",
                "3,0.75,hash-B,1,hash-Y",
            ]
        ),
        encoding="utf-8",
    )

    context = load_open_bandit_item_context(path)

    assert context[7]["item_feature_0"] == "0.25"
    assert context[7]["item_feature_1"] == "hash-A"
    assert context[7]["item_feature_2"] == "3"


def test_open_bandit_item_context_can_filter_to_logged_actions(tmp_path: Path) -> None:
    path = tmp_path / "item_context.csv"
    path.write_text(
        "\n".join(
            [
                "item_id,item_feature_0,item_feature_1",
                "7,0.25,A",
                "3,0.75,B",
            ]
        ),
        encoding="utf-8",
    )

    context = load_open_bandit_item_context(path, allowed_item_ids={3})

    assert set(context) == {3}


def test_open_bandit_item_context_rejects_implicit_schema_guessing(tmp_path: Path) -> None:
    path = tmp_path / "item_context.csv"
    path.write_text("id,feature\n7,A\n", encoding="utf-8")

    with pytest.raises(ValueError, match="item_id"):
        load_open_bandit_item_context(path)
