from __future__ import annotations

from collections.abc import Iterable, Sequence

import pytest

from growthevo.causal.dr_learner import CrossFittedDRLearner, LoggedTreatmentRecord
from growthevo.models import CausalBelief, Channel, GrowthAction, GrowthConstraints, GrowthOption
from growthevo.rl.model_based import RiskSensitiveMPC
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


class MeanRegressor:
    def __init__(self) -> None:
        self.mean = 0.0

    def fit(
        self,
        features: Iterable[Sequence[float]],
        targets: Iterable[float],
    ) -> "MeanRegressor":
        rows = list(features)
        ys = [float(value) for value in targets]
        if not rows or len(rows) != len(ys):
            raise ValueError("aligned non-empty data required")
        self.mean = sum(ys) / len(ys)
        return self

    def predict_one(self, features: Sequence[float]) -> float:
        tuple(features)
        return self.mean

    def predict(self, features: Iterable[Sequence[float]]) -> tuple[float, ...]:
        return tuple(self.predict_one(row) for row in features)


def _belief() -> CausalBelief:
    return CausalBelief(
        user_id="u",
        natural_conversion=0.15,
        channel_uplift={Channel.PUSH: 0.10},
        uplift_uncertainty=0.02,
        ltv=100.0,
        fatigue=0.1,
        churn_risk=0.1,
        touches_24h=0,
        touches_7d=0,
        spend_to_date=0.0,
        days_since_last_active=10,
        lifecycle_stage="active",
        consented_channels=frozenset({Channel.PUSH}),
    )


def _constraints() -> GrowthConstraints:
    return GrowthConstraints(
        max_budget=100.0,
        max_fatigue=1.0,
        max_churn_risk=1.0,
        max_touches_24h=20,
        max_touches_7d=20,
    )


def test_mpc_uses_common_random_numbers_for_identical_candidates() -> None:
    action = GrowthAction(
        option=GrowthOption.ACTIVATE,
        channel=Channel.PUSH,
        budget=0.1,
        frequency_cost=0.2,
        expected_uplift=0.08,
        uncertainty=0.01,
    )
    plan = (action, action, GrowthAction.no_treatment())
    planner = RiskSensitiveMPC(rollouts=12, base_seed=500)

    scores = planner.evaluate(
        _belief(),
        [("left", plan), ("right", plan)],
        _constraints(),
    )
    by_id = {score.candidate_id: score for score in scores}

    assert by_id["left"].mean_return == pytest.approx(by_id["right"].mean_return)
    assert by_id["left"].cvar_return == pytest.approx(by_id["right"].cvar_return)
    assert by_id["left"].violation_rate == pytest.approx(by_id["right"].violation_rate)


def test_mpc_candidate_order_does_not_change_scores() -> None:
    treatment = GrowthAction(
        option=GrowthOption.ACTIVATE,
        channel=Channel.PUSH,
        budget=0.1,
        frequency_cost=0.2,
        expected_uplift=0.08,
        uncertainty=0.01,
    )
    holdout = GrowthAction.no_treatment()
    planner = RiskSensitiveMPC(rollouts=10, base_seed=700)

    first = planner.evaluate(
        _belief(),
        [("treat", (treatment, treatment)), ("holdout", (holdout, holdout))],
        _constraints(),
    )
    second = planner.evaluate(
        _belief(),
        [("holdout", (holdout, holdout)), ("treat", (treatment, treatment))],
        _constraints(),
    )

    first_by_id = {score.candidate_id: score for score in first}
    second_by_id = {score.candidate_id: score for score in second}
    for candidate_id in first_by_id:
        assert first_by_id[candidate_id].mean_return == pytest.approx(
            second_by_id[candidate_id].mean_return
        )
        assert first_by_id[candidate_id].cvar_return == pytest.approx(
            second_by_id[candidate_id].cvar_return
        )


def test_ope_does_not_apply_untuned_robustness_constants() -> None:
    rows = [
        LoggedBanditRecord(
            reward=1.0,
            behavior_propensity=0.01,
            target_action_probability=0.5,
            baseline_q=0.2,
            target_q=0.3,
        ),
        LoggedBanditRecord(
            reward=0.0,
            behavior_propensity=0.5,
            target_action_probability=0.5,
            baseline_q=0.2,
            target_q=0.3,
        ),
    ]

    estimate = evaluate_policy(rows)

    assert estimate.switch_threshold is None
    assert estimate.dr_os_lambda is None
    assert estimate.switch_dr == pytest.approx(estimate.doubly_robust)
    assert estimate.dr_os == pytest.approx(estimate.doubly_robust)


def test_ope_support_coverage_tracks_importance_mass_not_row_fraction() -> None:
    estimate = evaluate_policy(
        [
            LoggedBanditRecord(
                reward=1.0,
                behavior_propensity=1e-4,
                target_action_probability=0.9,
                baseline_q=0.0,
                target_q=0.0,
            ),
            LoggedBanditRecord(
                reward=0.0,
                behavior_propensity=0.5,
                target_action_probability=0.1,
                baseline_q=0.0,
                target_q=0.0,
            ),
        ],
        support_propensity_floor=1e-3,
    )

    assert estimate.record_support_coverage == pytest.approx(0.5)
    assert estimate.support_coverage == pytest.approx(0.2 / 9000.2)
    assert estimate.mean_importance_weight > 1.0
    assert estimate.importance_weight_normalization_error > 0.0


def test_dr_learner_uses_injected_outcome_and_effect_backends() -> None:
    outcome_calls = 0
    effect_calls = 0

    def outcome_factory() -> MeanRegressor:
        nonlocal outcome_calls
        outcome_calls += 1
        return MeanRegressor()

    def effect_factory() -> MeanRegressor:
        nonlocal effect_calls
        effect_calls += 1
        return MeanRegressor()

    propensities = {Channel.NO_TREATMENT: 0.5, Channel.PUSH: 0.5}
    rows = []
    for index in range(8):
        action = Channel.PUSH if index % 2 else Channel.NO_TREATMENT
        rows.append(
            LoggedTreatmentRecord(
                unit_id=f"row-{index}",
                features=(float(index),),
                action=action,
                outcome=float(action is Channel.PUSH),
                action_propensities=propensities,
            )
        )

    model = CrossFittedDRLearner(
        n_folds=2,
        outcome_model_factory=outcome_factory,
        effect_model_factory=effect_factory,
    ).fit(rows, treatment=Channel.PUSH)

    assert outcome_calls == 4
    assert effect_calls == 3
    assert model.predict((2.0,)).effect == pytest.approx(1.0)
    assert model.residual_scale >= 0.0


def test_grouped_cross_fitting_keeps_same_group_in_one_fold() -> None:
    learner = CrossFittedDRLearner(n_folds=2)

    parity_seen: dict[int, str] = {}
    index = 0
    while len(parity_seen) < 2:
        candidate = f"group-{index}"
        parity = int.from_bytes(learner._stable_key(candidate), "big") % 2
        parity_seen.setdefault(parity, candidate)
        index += 1
    groups = [parity_seen[0], parity_seen[1]]

    propensities = {Channel.NO_TREATMENT: 0.5, Channel.PUSH: 0.5}
    rows: list[LoggedTreatmentRecord] = []
    for group_index, group_id in enumerate(groups):
        for action in (Channel.NO_TREATMENT, Channel.PUSH):
            rows.append(
                LoggedTreatmentRecord(
                    unit_id=f"{group_id}-{action.value}",
                    group_id=group_id,
                    features=(float(group_index),),
                    action=action,
                    outcome=float(action is Channel.PUSH),
                    action_propensities=propensities,
                )
            )

    assignments = learner._fold_assignments(rows, Channel.PUSH, Channel.NO_TREATMENT)
    by_group: dict[str, set[int]] = {}
    for row, fold in zip(rows, assignments, strict=True):
        by_group.setdefault(row.group_id or "", set()).add(fold)

    assert all(len(folds) == 1 for folds in by_group.values())
