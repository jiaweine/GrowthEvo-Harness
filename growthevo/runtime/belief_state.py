from __future__ import annotations

from growthevo.models import CausalBelief, UserObservation


def build_causal_belief(observation: UserObservation) -> CausalBelief:
    """Reduce observed growth features into the immutable policy belief state.

    This boundary deliberately separates observed natural conversion from
    treatment uplift. A policy must never reinterpret raw conversion as
    incremental effect.
    """

    return CausalBelief(
        user_id=observation.user_id,
        natural_conversion=observation.natural_conversion,
        channel_uplift=dict(observation.channel_uplift),
        uplift_uncertainty=observation.uplift_uncertainty,
        ltv=observation.ltv,
        fatigue=observation.fatigue,
        churn_risk=observation.churn_risk,
        touches_24h=observation.touches_24h,
        touches_7d=observation.touches_7d,
        spend_to_date=observation.spend_to_date,
        days_since_last_active=observation.days_since_last_active,
        lifecycle_stage=observation.lifecycle_stage,
        consented_channels=frozenset(observation.consented_channels),
    )
