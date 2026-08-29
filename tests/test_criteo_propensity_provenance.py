from __future__ import annotations

from pathlib import Path

import pytest

from growthevo.bench import load_criteo_uplift
from growthevo.models import Channel


def _header() -> str:
    return ",".join([*(f"f{i}" for i in range(12)), "treatment", "conversion", "visit", "exposure"])


def _row(offset: int, treatment: int) -> str:
    features = [str(offset + index / 100.0) for index in range(12)]
    return ",".join([*features, str(treatment), "0", str(treatment), str(treatment)])


def _fixture(tmp_path: Path) -> Path:
    path = tmp_path / "criteo.csv"
    path.write_text(
        "\n".join(
            [
                _header(),
                _row(0, 1),
                _row(1, 1),
                _row(2, 1),
                _row(3, 0),
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_criteo_empirical_propensity_is_labelled_as_fallback(tmp_path: Path) -> None:
    data = load_criteo_uplift(_fixture(tmp_path), outcome="visit")

    assert data.observed_treatment_share == pytest.approx(0.75)
    assert data.treatment_propensity == pytest.approx(0.75)
    assert data.propensity_source == "empirical"
    assert data.records[0].action_propensities[Channel.ADS] == pytest.approx(0.75)


def test_criteo_design_propensity_is_not_overwritten_by_loaded_arm_share(tmp_path: Path) -> None:
    data = load_criteo_uplift(
        _fixture(tmp_path),
        outcome="visit",
        treatment_propensity=0.60,
    )

    assert data.observed_treatment_share == pytest.approx(0.75)
    assert data.treatment_propensity == pytest.approx(0.60)
    assert data.propensity_source == "design"
    assert data.records[0].action_propensities[Channel.ADS] == pytest.approx(0.60)
