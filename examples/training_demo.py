from __future__ import annotations

from growthevo.bench import GrowthAgentBench
from growthevo.causal import CausalUpliftServingBridge
from growthevo.models import Channel, UserObservation, to_primitive
from growthevo.rl import (
    ActionValueEstimate,
    SafePolicyImprovementConfig,
    SupportAnchoredPolicyImprover,
)
from growthevo.training import PlannerTransition, TrajectoryTrainerAdapter


def main() -> None:
    bench = GrowthAgentBench.synthetic(sample_size=1000, seed=41, outcome_noise=0.015)
    push_model, push_metrics = bench.fit_cate(treatment=Channel.PUSH)
    email_model, email_metrics = bench.fit_cate(treatment=Channel.EMAIL)

    bridge = CausalUpliftServingBridge(
        {
            Channel.PUSH: push_model,
            Channel.EMAIL: email_model,
        }
    )
    observation = UserObservation(
        user_id="training-demo-user",
        natural_conversion=0.22,
        channel_uplift={Channel.PUSH: 0.0, Channel.EMAIL: 0.0},
        uplift_uncertainty=1.0,
        ltv=100.0,
        consented_channels=frozenset({Channel.PUSH, Channel.EMAIL}),
    )
    enriched, uplift = bridge.enrich_observation(observation, (0.20, -0.10))

    improver = SupportAnchoredPolicyImprover(
        SafePolicyImprovementConfig(max_total_variation=0.15)
    )
    policy = improver.improve(
        [
            ActionValueEstimate(
                action=Channel.NO_TREATMENT,
                value=0.0,
                value_uncertainty=0.01,
                behavior_probability=0.45,
                expected_cost=0.0,
            ),
            ActionValueEstimate(
                action=Channel.PUSH,
                value=enriched.channel_uplift[Channel.PUSH],
                value_uncertainty=uplift.channel_uncertainty[Channel.PUSH],
                behavior_probability=0.30,
                expected_cost=0.04,
                cost_uncertainty=0.005,
            ),
            ActionValueEstimate(
                action=Channel.EMAIL,
                value=enriched.channel_uplift[Channel.EMAIL],
                value_uncertainty=uplift.channel_uncertainty[Channel.EMAIL],
                behavior_probability=0.25,
                expected_cost=0.02,
                cost_uncertainty=0.003,
            ),
        ],
        max_expected_cost=0.05,
    )

    trainer_batch = TrajectoryTrainerAdapter(
        normalize_advantages=False,
    ).build(
        [
            PlannerTransition(
                trajectory_id="growth-plan-1",
                step_index=0,
                action="estimate_uplift",
                observation={
                    "minimum_support": uplift.minimum_support,
                    "aggregate_uncertainty": uplift.aggregate_uncertainty,
                },
                reward=0.10,
                value_estimate=0.05,
                next_value_estimate=0.08,
            ),
            PlannerTransition(
                trajectory_id="growth-plan-1",
                step_index=1,
                action=f"select:{policy.selected_action.value}",
                observation={
                    "changed": policy.changed,
                    "total_variation": policy.total_variation_distance,
                },
                reward=0.20,
                value_estimate=0.08,
                done=True,
                legal_action=True,
            ),
        ]
    )

    print("=== Held-out CATE benchmark ===")
    print("push:", to_primitive(push_metrics))
    print("email:", to_primitive(email_metrics))

    print("\n=== CATE serving ===")
    print("enriched_observation:", to_primitive(enriched))
    print("uplift_prediction:", to_primitive(uplift))

    print("\n=== Support-anchored policy improvement ===")
    print("policy:", to_primitive(policy))

    print("\n=== Planner training export ===")
    print(trainer_batch.to_jsonl())


if __name__ == "__main__":
    main()
