from __future__ import annotations

from pathlib import Path

from growthevo.bench import load_kuairand_user_features, load_kuairand_video_features


def test_user_features_preserve_categorical_fields(tmp_path: Path) -> None:
    path = tmp_path / "user_features.csv"
    path.write_text(
        "\n".join(
            [
                "user_id,user_active_degree,is_lowactive_period,follow_user_num,follow_user_num_range",
                "1,full_active,0,5,(0;10]",
                "2,middle_active,1,120,(100;150]",
            ]
        ),
        encoding="utf-8",
    )

    features = load_kuairand_user_features(path, user_ids={2})

    assert set(features) == {2}
    assert features[2]["user_active_degree"] == "middle_active"
    assert features[2]["is_lowactive_period"] == 1
    assert features[2]["follow_user_num"] == 120


def test_video_features_can_be_filtered_to_logged_actions(tmp_path: Path) -> None:
    path = tmp_path / "video_features_basic.csv"
    path.write_text(
        "\n".join(
            [
                "video_id,author_id,video_type,upload_dt,upload_type,visible_status,video_duration,server_width,server_height,music_id,music_type,tag",
                "10,7,NORMAL,2020-07-08,ShortImport,1,17200,720,1280,99,4,12",
                "11,8,AD,2020-07-09,Web,1,9100,720,1280,100,2,65",
                "12,9,NORMAL,2020-07-10,ShortImport,1,8200,720,1280,101,3,18",
            ]
        ),
        encoding="utf-8",
    )

    features = load_kuairand_video_features(path, video_ids={10, 12})

    assert set(features) == {10, 12}
    assert features[10]["video_type"] == "NORMAL"
    assert features[10]["video_duration"] == 17200
    assert features[12]["music_type"] == 3
