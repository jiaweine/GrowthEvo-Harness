from __future__ import annotations

from growthevo.models import (
    Channel,
    GrowthConstraints,
    GrowthGoal,
    PolicyEvidence,
    UserObservation,
    to_primitive,
)
from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy
from growthevo.runtime.engine import GrowthEvoRuntime


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

    runtime = GrowthEvoRuntime()
    result = runtime.run(goal, observation)

    print("=== Runtime decision ===")
    print(to_primitive(result))
    print("event_chain_valid:", runtime.event_store.verify())

    # A small logged-bandit cohort demonstrates the promotion path. Interaction
    # execution and cohort policy promotion remain separate phases, while both
    # are persisted into the same event stream.
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
    ope = evaluate_policy(records)
    evidence = PolicyEvidence(
        candidate_value=ope.doubly_robust,
        baseline_value=0.25,
        standard_error=0.02,
        sample_size=ope.sample_size,
        effective_sample_size=ope.effective_sample_size,
        roi=2.2,
        spend=68.0,
        fatigue=0.31,
        churn_risk=0.20,
    )
    verification = runtime.verify_candidate(evidence, constraints)

    print("\n=== Counterfactual policy gate ===")
    print("ope:", to_primitive(ope))
    print("verification:", to_primitive(verification))
    print("event_count_after_verification:", len(runtime.event_store))
    print("event_chain_valid:", runtime.event_store.verify())


if __name__ == "__main__":
    main()
