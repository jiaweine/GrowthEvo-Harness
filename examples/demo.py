from __future__ import annotations

from growthevo.models import (
    Channel,
    GrowthConstraints,
    GrowthGoal,
    UserObservation,
    to_primitive,
)
from growthevo.rl.conformal import ConformalCalibrationRecord, ConformalPolicyCalibrator
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy, policy_evidence_from_ope
from growthevo.rl.process_reward import ProcessState, TrajectoryStepSignal
from growthevo.runtime.engine import GrowthEvoRuntime
from growthevo.verifier.counterfactual import (
    CounterfactualVerifier,
    ThresholdEvidenceGate,
    VerifierConfig,
)


def main() -> None:
    constraints = GrowthConstraints(
        max_budget=100.0,
        min_roi=1.5,
        max_fatigue=0.8,
        max_churn_risk=0.5,
    )
    goal = GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=constraints,
    )
    observation = UserObservation(
        user_id="demo-dormant-user",
        natural_conversion=0.18,
        channel_uplift={
            Channel.PUSH: 0.08,
            Channel.EMAIL: 0.04,
            Channel.IN_APP: 0.02,
        },
        uplift_uncertainty=0.05,
        channel_support={
            Channel.PUSH: 0.90,
            Channel.EMAIL: 0.85,
            Channel.IN_APP: 0.80,
        },
        ltv=120.0,
        fatigue=0.12,
        churn_risk=0.18,
        touches_24h=0,
        touches_7d=1,
        spend_to_date=10.0,
        days_since_last_active=45,
        lifecycle_stage="dormant",
        consented_channels=frozenset({Channel.PUSH, Channel.EMAIL, Channel.IN_APP}),
    )

    # The demo chooses one explicit reference promotion protocol. These values are
    # not defaults in the Runtime/Verifier and must not be treated as universal
    # deployment thresholds.
    verifier = CounterfactualVerifier(
        VerifierConfig(z_score=1.96),
        evidence_gate=ThresholdEvidenceGate(
            min_sample_size=50,
            min_effective_sample_size=40.0,
            min_effective_sample_ratio=0.50,
            min_support_coverage=0.95,
            max_importance_weight=5.0,
        ),
    )
    runtime = GrowthEvoRuntime(verifier=verifier)
    result = runtime.run(goal, observation)

    print("=== Runtime decision ===")
    print(to_primitive(result))
    print("event_chain_valid:", runtime.event_store.verify())

    trajectory_reward = runtime.score_planner_trajectory(
        [
            TrajectoryStepSignal(
                step_id="segment-evidence",
                before=ProcessState(0.10, 0.20, 0.80),
                after=ProcessState(0.25, 0.45, 0.80),
                action_entropy=0.20,
                tool_success=True,
                direct_cost=0.01,
            ),
            TrajectoryStepSignal(
                step_id="uplift-evidence",
                before=ProcessState(0.25, 0.45, 0.80),
                after=ProcessState(0.50, 0.70, 0.75),
                action_entropy=0.15,
                tool_success=True,
                direct_cost=0.02,
            ),
        ],
        terminal_outcome=0.20,
    )

    records = [
        LoggedBanditRecord(
            reward=1.0 if index % 3 == 0 else 0.0,
            behavior_propensity=0.5,
            target_action_probability=0.5,
            baseline_q=0.35,
            target_q=0.40,
        )
        for index in range(80)
    ]
    # Practical support is also part of the declared demo protocol. OPE can be
    # inspected without it, but promotion evidence cannot be compiled without an
    # explicit support definition.
    ope = evaluate_policy(records, support_propensity_floor=0.05)
    evidence = policy_evidence_from_ope(
        ope,
        baseline_value=0.15,
        roi=2.2,
        spend=68.0,
        fatigue=0.31,
        churn_risk=0.20,
    )

    # Five simultaneous calibrated gate metrics at gate alpha=0.05 imply a
    # Bonferroni per-metric alpha of 0.01. A 100-cohort fixture is used so the
    # finite-sample conformal order statistic actually exists; the calibrator no
    # longer clips an unattainable rank to the largest observed residual.
    conformal = ConformalPolicyCalibrator(
        alpha=0.05,
        simultaneous=True,
        min_calibration_size=100,
    ).fit(
        ConformalCalibrationRecord(
            predicted_value_delta=0.20,
            observed_value_delta=0.19,
            predicted_roi=2.20,
            observed_roi=2.15,
            predicted_spend=68.0,
            observed_spend=69.0,
            predicted_fatigue=0.31,
            observed_fatigue=0.32,
            predicted_churn_risk=0.20,
            observed_churn_risk=0.21,
        )
        for _ in range(100)
    )
    verification = runtime.verify_candidate(evidence, constraints, conformal=conformal)

    print("\n=== Growth process reward ===")
    print(to_primitive(trajectory_reward))
    print("\n=== Counterfactual policy gate ===")
    print("ope:", to_primitive(ope))
    print("conformal:", to_primitive(conformal))
    print("verification:", to_primitive(verification))
    print("event_count_after_verification:", len(runtime.event_store))
    print("event_chain_valid:", runtime.event_store.verify())


if __name__ == "__main__":
    main()
