from __future__ import annotations

from collections import Counter

from growthevo.causal.dr_learner import CrossFittedDRLearner, LoggedTreatmentRecord
from growthevo.models import Channel


def _rows() -> list[LoggedTreatmentRecord]:
    propensities = {Channel.NO_TREATMENT: 0.5, Channel.PUSH: 0.5}
    specs = {
        "large-treatment": (8, 1),
        "large-control": (1, 8),
        "balanced-a": (4, 4),
        "balanced-b": (4, 4),
        "small-treatment": (3, 1),
        "small-control": (1, 3),
    }
    rows: list[LoggedTreatmentRecord] = []
    index = 0
    for group_id, (treated, control) in specs.items():
        for action, count in (
            (Channel.PUSH, treated),
            (Channel.NO_TREATMENT, control),
        ):
            for _ in range(count):
                rows.append(
                    LoggedTreatmentRecord(
                        unit_id=f"row-{index}",
                        group_id=group_id,
                        features=(float(index),),
                        action=action,
                        outcome=float(action is Channel.PUSH),
                        action_propensities=propensities,
                    )
                )
                index += 1
    return rows


def test_grouped_crossfit_keeps_groups_intact_and_balances_actions() -> None:
    rows = _rows()
    learner = CrossFittedDRLearner(n_folds=3)

    assignments = learner._fold_assignments(rows, Channel.PUSH, Channel.NO_TREATMENT)

    group_folds: dict[str, set[int]] = {}
    by_fold: dict[int, Counter[Channel]] = {fold: Counter() for fold in range(3)}
    for row, fold in zip(rows, assignments, strict=True):
        group_folds.setdefault(row.group_id or "", set()).add(fold)
        by_fold[fold][row.action] += 1

    assert all(len(folds) == 1 for folds in group_folds.values())
    assert all(sum(counts.values()) > 0 for counts in by_fold.values())

    treatment_counts = [by_fold[fold][Channel.PUSH] for fold in range(3)]
    control_counts = [by_fold[fold][Channel.NO_TREATMENT] for fold in range(3)]

    # The largest single-action group contains eight rows, so no deterministic
    # group-preserving method can guarantee a tighter worst-case spread here.
    assert max(treatment_counts) - min(treatment_counts) <= 8
    assert max(control_counts) - min(control_counts) <= 8


def test_grouped_crossfit_rejects_too_few_distinct_groups() -> None:
    propensities = {Channel.NO_TREATMENT: 0.5, Channel.PUSH: 0.5}
    rows = [
        LoggedTreatmentRecord(
            unit_id=f"row-{index}",
            group_id="only-group",
            features=(float(index),),
            action=Channel.PUSH if index % 2 else Channel.NO_TREATMENT,
            outcome=float(index % 2),
            action_propensities=propensities,
        )
        for index in range(8)
    ]

    learner = CrossFittedDRLearner(n_folds=2)

    try:
        learner._fold_assignments(rows, Channel.PUSH, Channel.NO_TREATMENT)
    except ValueError as exc:
        assert "distinct groups" in str(exc)
    else:  # pragma: no cover - regression guard.
        raise AssertionError("expected too-few-group validation to fail")
