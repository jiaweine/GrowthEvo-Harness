from __future__ import annotations

import pytest

from growthevo.models import (
    CausalBelief,
    Channel,
    GrowthAction,
    GrowthConstraints,
    GrowthOption,
    PolicyEvidence,
    VerificationStatus,
)
from growthevo.rl.conformal import (
    ConformalCalibrationRecord,
    ConformalPolicyCalibrator,
)
from growthevo.rl.model_based import RiskSensitiveMPC
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy
from growthevo.rl.process_reward import (
    GrowthProcessRewardModel,
    ProcessState,
    TrajectoryStepSignal,
)
from growthevo.verifier.counterfactual import CounterfactualVerifier, VerifierConfig


def _constraints(**overrides: object) -> GrowthConstraints:
    values: dict[str, object] = {
        "max_budget": 100.0,
        "min_roi": 1.0,
        "max_fatigue": 0.8,
        "max_churn_risk": 0.5,
        "max_touches_24h": 4,
        "max_touches_7d": 10,
        "max_offer_value": 20.0,
    }
    values.update(overrides)
    return GrowthConstraints(**values)  # type: ignore[arg-type]


def _belief() -> CausalBelief:
    return CausalBelief(
        user_id="frontier-u1",
        natural_conversion=0.15,
        channel_uplift={Channel.PUSH: 0.10, Channel.EMAIL: 0.05},
        uplift_uncertainty=0.02,
        ltv=100.0,
        fatigue=0.10,
        churn_risk=0.10,
        touches_24h=0,
        touches_7d=0,
        spend_to_date=0.0,
        days_since_last_active=30,
        lifecycle_stage="dormant",
        consented_channels=frozenset({Channel.PUSH, Channel.EMAIL}),
    )


def test_beta_star_ips_removes_linear_weight_variance() -> None:
    rows = []
    for target_probability, reward in (
        (0.25, 0.0),
        (0.50, 1.0),
        (0.75, 4.0 / 3.0),
        (1.00, 1.5),
    ):
        rows.append(
            LoggedBanditRecord(
                reward=reward,
                behavior_propensity=0.5,
                target_action_probability=target_probability,
                baseline_q=0.0,
                target_q=0.0,
            )
        )

    estimate = evaluate_policy(rows)

    assert estimate.beta_star == pytest.approx(2.0)
    assert estimate.beta_ips == pytest.approx(1.0)
    assert estimate.beta_ips_standard_error == pytest.approx(0.0, abs=1e-12)
    assert estimate.ips_standard_error > estimate.beta_ips_standard_error
    assert estimate.effective_sample_ratio < 1.0


def test_ope_reports_target_mass_support_gap() -> None:
    estimate = evaluate_policy(
        [
            LoggedBanditRecord(
                reward=1.0,
                behavior_propensity=1e-4,
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
        ],
        support_propensity_floor=1e-3,
    )

    assert estimate.record_support_coverage == pytest.approx(0.5)
    assert estimate.support_coverage == pytest.approx(1.0 / 5001.0)
    assert estimate.max_importance_weight == pytest.approx(5000.0)


def test_conformal_margins_are_residual_margins_not_absolute_bounds() -> None:
    calibration = ConformalPolicyCalibrator(alpha=0.05, min_calibration_size=30).fit(
        ConformalCalibrationRecord(
            predicted_value_delta=0.20,
            observed_value_delta=0.15,
            predicted_roi=2.0,
            observed_roi=1.8,
            predicted_spend=50.0,
            observed_spend=55.0,
            predicted_fatigue=0.30,
            observed_fatigue=0.35,
            predicted_churn_risk=0.20,
            observed_churn_risk=0.24,
        )
        for _ in range(30)
    )

    assert calibration.value_lower_margin == pytest.approx(0.05)
    assert calibration.roi_lower_margin == pytest.approx(0.20)
    assert calibration.spend_upper_margin == pytest.approx(5.0)
    assert calibration.fatigue_upper_margin == pytest.approx(0.05)
    assert calibration.churn_risk_upper_margin == pytest.approx(0.04)
    assert calibration.per_metric_alpha == pytest.approx(0.01)

    assert calibration.value_lcb(0.20) == pytest.approx(0.15)
    assert calibration.roi_lcb(2.0) == pytest.approx(1.8)
    assert calibration.spend_ucb(50.0) == pytest.approx(55.0)
    assert calibration.fatigue_ucb(0.30) == pytest.approx(0.35)
    assert calibration.churn_risk_ucb(0.20) == pytest.approx(0.24)


def test_conformal_familywise_correction_is_stricter_than_marginal_calibration() -> None:
    records = [
        ConformalCalibrationRecord(
            predicted_value_delta=1.0,
            observed_value_delta=1.0 - index / 100.0,
            predicted_roi=2.0,
            observed_roi=2.0,
            predicted_spend=50.0,
            observed_spend=50.0,
            predicted_fatigue=0.30,
            observed_fatigue=0.30,
            predicted_churn_risk=0.20,
            observed_churn_risk=0.20,
        )
        for index in range(100)
    ]

    familywise = ConformalPolicyCalibrator(
        alpha=0.05,
        min_calibration_size=30,
    ).fit(records)
    marginal = ConformalPolicyCalibrator(
        alpha=0.05,
        min_calibration_size=30,
        simultaneous=False,
    ).fit(records)

    assert familywise.per_metric_alpha == pytest.approx(0.01)
    assert marginal.per_metric_alpha == pytest.approx(0.05)
    assert familywise.value_lower_margin == pytest.approx(0.99)
    assert marginal.value_lower_margin == pytest.approx(0.95)
    assert familywise.value_lower_margin > marginal.value_lower_margin


def test_conformal_gate_can_block_statistically_positive_candidate() -> None:
    calibration = ConformalPolicyCalibrator(alpha=0.05, min_calibration_size=30).fit(
        ConformalCalibrationRecord(
            predicted_value_delta=0.20,
            observed_value_delta=0.15,
            predicted_roi=2.0,
            observed_roi=1.8,
            predicted_spend=50.0,
            observed_spend=55.0,
            predicted_fatigue=0.30,
            observed_fatigue=0.35,
            predicted_churn_risk=0.20,
            observed_churn_risk=0.24,
        )
        for _ in range(30)
    )
    evidence = PolicyEvidence(
        candidate_value=1.20,
        baseline_value=1.00,
        standard_error=0.01,
        sample_size=100,
        effective_sample_size=90,
        roi=1.90,
        spend=50.0,
        fatigue=0.30,
        churn_risk=0.20,
    )
    constraints = _constraints(max_budget=54.0, min_roi=1.8)
    verifier = CounterfactualVerifier()

    assert verifier.verify(evidence, constraints).status is VerificationStatus.PASS
    calibrated = verifier.verify(evidence, constraints, conformal=calibration)

    assert calibrated.status is VerificationStatus.FAIL
    assert "roi_constraint_violated" in calibrated.reasons
    assert "budget_constraint_violated" in calibrated.reasons


def test_verifier_abstains_when_logging_support_is_weak() -> None:
    evidence = PolicyEvidence(
        candidate_value=1.3,
        baseline_value=1.0,
        standard_error=0.02,
        sample_size=200,
        effective_sample_size=120,
        roi=2.0,
        spend=10.0,
        fatigue=0.2,
        churn_risk=0.1,
        support_coverage=0.80,
        max_importance_weight=5.0,
    )

    result = CounterfactualVerifier().verify(evidence, _constraints())

    assert result.status is VerificationStatus.INSUFFICIENT_EVIDENCE
    assert "logging_support_below_gate" in result.reasons


def test_verifier_rejects_negative_standard_error_instead_of_fail_open() -> None:
    evidence = PolicyEvidence(
        candidate_value=1.3,
        baseline_value=1.0,
        standard_error=-0.01,
        sample_size=200,
        effective_sample_size=120,
        roi=2.0,
        spend=10.0,
        fatigue=0.2,
        churn_risk=0.1,
    )

    with pytest.raises(ValueError, match="standard_error"):
        CounterfactualVerifier().verify(evidence, _constraints())


def test_verifier_config_rejects_invalid_probability_thresholds() -> None:
    with pytest.raises(ValueError, match="min_support_coverage"):
        VerifierConfig(min_support_coverage=1.1)
    with pytest.raises(ValueError, match="min_effective_sample_ratio"):
        VerifierConfig(min_effective_sample_ratio=-0.1)


def test_growth_prm_rewards_grounded_information_gain() -> None:
    before = ProcessState(goal_progress=0.2, evidence_quality=0.2, constraint_slack=0.8)
    after = ProcessState(goal_progress=0.3, evidence_quality=0.5, constraint_slack=0.8)
    model = GrowthProcessRewardModel()

    confident = model.score_step(
        TrajectoryStepSignal(
            step_id="query-user-history",
            before=before,
            after=after,
            action_entropy=0.1,
            tool_success=True,
        )
    )
    uncertain = model.score_step(
        TrajectoryStepSignal(
            step_id="query-user-history-uncertain",
            before=before,
            after=after,
            action_entropy=0.9,
            tool_success=True,
        )
    )

    assert confident.observation_credit > uncertain.observation_credit
    assert confident.total > uncertain.total


def test_growth_prm_penalizes_duplicate_failed_side_effect() -> None:
    state = ProcessState(goal_progress=0.4, evidence_quality=0.5, constraint_slack=0.5)
    result = GrowthProcessRewardModel().score_step(
        TrajectoryStepSignal(
            step_id="bad-step",
            before=state,
            after=state,
            action_entropy=0.2,
            tool_success=False,
            direct_cost=1.0,
            duplicate_evidence=True,
            irreversible_side_effect=True,
        )
    )

    assert result.total < 0
    assert result.side_effect_penalty > 0


def test_risk_sensitive_mpc_prefers_safe_holdout_to_budget_violating_plan() -> None:
    treatment = GrowthAction(
        option=GrowthOption.REACTIVATE,
        channel=Channel.PUSH,
        budget=0.5,
        frequency_cost=1.0,
        expected_uplift=0.10,
        uncertainty=0.01,
    )
    holdout = GrowthAction.no_treatment()
    planner = RiskSensitiveMPC(rollouts=8, cvar_alpha=0.25, violation_penalty=2.0)

    scores = planner.evaluate(
        _belief(),
        [
            ("aggressive", (treatment, treatment, treatment)),
            ("holdout", (holdout, holdout, holdout)),
        ],
        _constraints(max_budget=1.0),
    )

    by_id = {score.candidate_id: score for score in scores}
    assert by_id["aggressive"].violation_rate == pytest.approx(1.0)
    assert by_id["holdout"].violation_rate == pytest.approx(0.0)
    assert scores[0].candidate_id == "holdout"
