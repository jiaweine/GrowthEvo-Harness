from __future__ import annotations

from growthevo.models import (
    Channel,
    EventType,
    GrowthConstraints,
    GrowthGoal,
    PolicyEvidence,
    UserObservation,
    VerificationStatus,
)
from growthevo.runtime.engine import GrowthEvoRuntime


def test_runtime_persists_cohort_verification_in_same_event_chain() -> None:
    constraints = GrowthConstraints(max_budget=100.0, min_roi=1.0)
    goal = GrowthGoal(
        metric="incremental_ltv",
        horizon_days=30,
        target_delta=0.05,
        constraints=constraints,
    )
    observation = UserObservation(
        user_id="u-verify",
        natural_conversion=0.20,
        channel_uplift={Channel.PUSH: 0.08},
        uplift_uncertainty=0.05,
        ltv=100.0,
        days_since_last_active=40,
        lifecycle_stage="dormant",
        consented_channels=frozenset({Channel.PUSH}),
    )
    runtime = GrowthEvoRuntime()
    runtime.run(goal, observation)

    evidence = PolicyEvidence(
        candidate_value=1.30,
        baseline_value=1.00,
        standard_error=0.05,
        sample_size=100,
        effective_sample_size=80.0,
        roi=2.0,
        spend=20.0,
        fatigue=0.2,
        churn_risk=0.1,
    )
    result = runtime.verify_candidate(evidence, constraints)

    assert result.status is VerificationStatus.PASS
    assert runtime.event_store.events()[-1].event_type is EventType.VERIFICATION_COMPLETED
    assert runtime.event_store.verify()
