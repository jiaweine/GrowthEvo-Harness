from __future__ import annotations

from pathlib import Path

from growthevo.bench import deterministic_stratified_split, load_criteo_uplift


def _header() -> str:
    return ",".join([*(f"f{i}" for i in range(12)), "treatment", "conversion", "visit", "exposure"])


def _row(offset: int, treatment: int, visit: int) -> str:
    features = [str(offset + index / 100.0) for index in range(12)]
    return ",".join([*features, str(treatment), "0", str(visit), "0"])


def _write(path: Path, rows: list[str]) -> Path:
    path.write_text("\n".join([_header(), *rows]), encoding="utf-8")
    return path


def _split_ids(path: Path) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    data = load_criteo_uplift(path, treatment_propensity=0.5)
    split = deterministic_stratified_split(
        data.records,
        identity=lambda row: row.unit_id,
        stratum=lambda row: row.action.value,
        train_fraction=0.5,
        validation_fraction=0.25,
        seed=19,
    )
    return (
        frozenset(row.unit_id for row in split.train),
        frozenset(row.unit_id for row in split.validation),
        frozenset(row.unit_id for row in split.test),
    )


def test_criteo_split_identity_is_stable_under_source_row_reordering(tmp_path: Path) -> None:
    rows = [
        _row(0, 1, 1),
        _row(1, 0, 0),
        _row(2, 1, 0),
        _row(3, 0, 1),
        _row(4, 1, 1),
        _row(5, 0, 0),
        _row(6, 1, 0),
        _row(7, 0, 1),
    ]
    first = _write(tmp_path / "first.csv", rows)
    second = _write(tmp_path / "second.csv", list(reversed(rows)))

    assert _split_ids(first) == _split_ids(second)


def test_exact_duplicate_rows_receive_unique_but_stable_id_multiset(tmp_path: Path) -> None:
    duplicate = _row(0, 1, 1)
    control_a = _row(1, 0, 0)
    control_b = _row(2, 0, 1)
    first = _write(tmp_path / "duplicates-a.csv", [duplicate, control_a, duplicate, control_b])
    second = _write(tmp_path / "duplicates-b.csv", [control_b, duplicate, control_a, duplicate])

    first_ids = sorted(row.unit_id for row in load_criteo_uplift(first).records)
    second_ids = sorted(row.unit_id for row in load_criteo_uplift(second).records)

    assert len(first_ids) == len(set(first_ids))
    assert first_ids == second_ids
