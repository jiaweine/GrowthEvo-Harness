from __future__ import annotations

from dataclasses import dataclass

from growthevo.bench.splits import deterministic_stratified_split, ordered_split


@dataclass(frozen=True)
class Row:
    row_id: str
    arm: str
    order: int


def _rows() -> list[Row]:
    return [
        Row(row_id=f"{arm}-{index}", arm=arm, order=index)
        for arm in ("control", "treatment")
        for index in range(6)
    ]


def test_stratified_split_is_source_order_invariant_and_covers_each_arm() -> None:
    rows = _rows()
    first = deterministic_stratified_split(
        rows,
        identity=lambda row: row.row_id,
        stratum=lambda row: row.arm,
        train_fraction=0.50,
        validation_fraction=0.25,
        seed=41,
    )
    second = deterministic_stratified_split(
        reversed(rows),
        identity=lambda row: row.row_id,
        stratum=lambda row: row.arm,
        train_fraction=0.50,
        validation_fraction=0.25,
        seed=41,
    )

    assert first == second
    assert first.total_size == len(rows)
    for partition in (first.train, first.validation, first.test):
        assert {row.arm for row in partition} == {"control", "treatment"}


def test_stratified_split_changes_assignment_when_seed_changes() -> None:
    rows = _rows()
    first = deterministic_stratified_split(
        rows,
        identity=lambda row: row.row_id,
        stratum=lambda row: row.arm,
        train_fraction=0.50,
        validation_fraction=0.25,
        seed=1,
    )
    second = deterministic_stratified_split(
        rows,
        identity=lambda row: row.row_id,
        stratum=lambda row: row.arm,
        train_fraction=0.50,
        validation_fraction=0.25,
        seed=2,
    )

    assert {row.row_id for row in first.train} != {row.row_id for row in second.train}


def test_ordered_split_respects_declared_order_not_input_order() -> None:
    rows = [Row(row_id=f"row-{index}", arm="all", order=index) for index in range(10)]
    split = ordered_split(
        reversed(rows),
        order_key=lambda row: row.order,
        identity=lambda row: row.row_id,
        train_fraction=0.60,
        validation_fraction=0.20,
    )

    assert [row.order for row in split.train] == list(range(6))
    assert [row.order for row in split.validation] == [6, 7]
    assert [row.order for row in split.test] == [8, 9]


def test_split_rejects_duplicate_identities() -> None:
    rows = [Row(row_id="same", arm="a", order=0), Row(row_id="same", arm="a", order=1)]

    try:
        deterministic_stratified_split(
            rows,
            identity=lambda row: row.row_id,
            stratum=lambda row: row.arm,
            train_fraction=0.50,
            validation_fraction=0.0,
            seed=3,
        )
    except ValueError as exc:
        assert "identities must be unique" in str(exc)
    else:  # pragma: no cover - regression guard.
        raise AssertionError("expected duplicate split identity validation to fail")
