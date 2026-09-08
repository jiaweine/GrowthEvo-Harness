# Production operator JSON schemas

The production operator surface uses three deliberately small JSON envelopes. All parsers are strict: unknown keys are rejected rather than silently ignored.

## Operator manifest

Schema version: `growthevo.production-operator-manifest.v1`

Required top-level fields:

```json
{
  "schema_version": "growthevo.production-operator-manifest.v1",
  "benchmark": "locked-benchmark-id",
  "dataset": "locked-case-set-id",
  "dataset_source": "versioned-source-id",
  "evidence_producer": {
    "name": "producer-name",
    "version": "producer-version"
  },
  "candidates": []
}
```

Optional top-level gates mirror `LLMExperimentPlan`: `trials_per_case`, `z_value`, decision/fallback/evidence violation gates, support/ESS thresholds, `require_promotion_evidence`, and `evidence_contract`.

Each candidate contains:

```json
{
  "name": "candidate-id",
  "endpoint": {
    "provider": "openai",
    "model": "pinned-model-snapshot",
    "reasoning_effort": "medium",
    "store": false
  },
  "planner_config": {
    "shadow_mode": true
  }
}
```

Supported providers are `openai`, `anthropic`, and `google`. Anthropic can declare `max_tokens`; OpenAI can declare `reasoning_effort` and `store`. A `critic_endpoint` can be supplied as a second endpoint object.

No authentication field exists. Keys such as `api_key`, bearer tokens, project secrets, private keys, or credential payloads are not valid manifest fields.

## Context file

Schema version: `growthevo.operator-contexts.v1`

```json
{
  "schema_version": "growthevo.operator-contexts.v1",
  "cases": [
    {
      "case_id": "case-001",
      "belief": {
        "user_id": "internal-analysis-unit",
        "natural_conversion": 0.1,
        "channel_uplift": {"email": 0.03},
        "uplift_uncertainty": 0.1,
        "ltv": 100.0,
        "fatigue": 0.1,
        "churn_risk": 0.2,
        "touches_24h": 0,
        "touches_7d": 1,
        "spend_to_date": 0.0,
        "days_since_last_active": 2,
        "lifecycle_stage": "active",
        "consented_channels": ["email"]
      },
      "goal": {
        "metric": "incremental_ltv",
        "horizon_days": 30,
        "target_delta": 0.05,
        "constraints": {"max_budget": 10.0}
      },
      "baseline_option": "retain",
      "weight": 1.0
    }
  ]
}
```

The context fingerprint binds case ID, exact `CausalBelief`, exact `GrowthGoal`, baseline semantic option and case weight. The `context-fingerprints` CLI intentionally emits only case IDs and fingerprints, not `user_id`.

## Causal evidence file

Schema version: `growthevo.operator-causal-evidence.v1`

Validation and holdout use separate files with the same envelope:

```json
{
  "schema_version": "growthevo.operator-causal-evidence.v1",
  "producer": {
    "name": "producer-name",
    "version": "producer-version"
  },
  "bundles": [
    {
      "case_id": "case-001",
      "context_fingerprint": "40-hex-character-context-fingerprint",
      "estimand": "incremental value vs no treatment",
      "estimates": [
        {
          "option": "retain",
          "value": 0.01,
          "standard_error": 0.002,
          "tier": "tier_a_randomized_experiment",
          "source_id": "experiment:locked-id",
          "protocol_fingerprint": "protocol-fingerprint",
          "support_coverage": 1.0,
          "effective_sample_ratio": 0.8,
          "feasible": true,
          "sample_size": 10000
        }
      ]
    }
  ]
}
```

Allowed evidence tiers are:

- `tier_a_randomized_experiment`
- `tier_b_preregistered_ope`
- `tier_c_model_based`
- `tier_d_proxy`

Only Tier A/B are promotion eligible when the operator manifest requires promotion evidence.

The producer name/version must exactly match the operator manifest. Every split's evidence case-ID set must exactly equal its context case-ID set. Validation and holdout case IDs must be disjoint, and every evidence bundle must match the exact context fingerprint before it can be scored.
