# Locked Randomized Targeting Run

`growthevo-locked-targeting` selects a targeting/CATE score model using randomized validation evidence and evaluates only the frozen winner on final holdout.

For promotable Criteo-style evidence, use the preregistered path rather than an ad-hoc final-test model comparison.

## Pre-registered command

```bash
growthevo-locked-targeting \
  --tuning-jsonl validation.jsonl \
  --test-jsonl holdout.jsonl \
  --selected-fraction 0.10 \
  --treatment ads \
  --benchmark criteo-uplift-targeting \
  --dataset criteo-uplift-v2 \
  --commit-sha "$(git rev-parse HEAD)" \
  --experiment-plan-json targeting-plan.json \
  --export-manifest-json targeting-export-manifest.json \
  --output targeting-result.json
```

`--experiment-plan-json` and `--export-manifest-json` must be supplied together. Plan/manifest/runtime disagreement fails before validation evidence is opened.

## Targeting experiment plan

`growthevo.targeting-experiment-plan.v1` freezes:

- benchmark and dataset identity;
- dataset source/release identity;
- outcome definition;
- split strategy and validation fraction;
- treatment arm;
- selected top fraction;
- score-generation protocol identifier;
- complete candidate-name set.

Example:

```json
{
  "schema_version": "growthevo.targeting-experiment-plan.v1",
  "benchmark": "criteo-uplift-targeting",
  "dataset": "criteo-uplift-v2",
  "dataset_source": "criteo-uplift-v2:<release-or-file-digest>",
  "outcome_definition": "conversion",
  "split_strategy": "stable_hash_unit_id_v1",
  "validation_fraction": 0.2,
  "treatment": "ads",
  "selected_fraction": 0.1,
  "score_protocol": "<predeclared-training-and-cross-fitting-protocol>",
  "candidate_names": ["candidate-a", "candidate-b"]
}
```

The repository does not invent a canonical Criteo model list. Candidate names should correspond to real score-generation pipelines fixed before validation, such as a specified DR learner/backend, causal forest, boosted uplift model, or another externally trained candidate.

## Realized targeting manifest

The companion `growthevo.targeting-export.v1` manifest records what was actually materialized:

```json
{
  "schema_version": "growthevo.targeting-export.v1",
  "dataset_source": "criteo-uplift-v2:<release-or-file-digest>",
  "outcome_definition": "conversion",
  "split_strategy": "stable_hash_unit_id_v1",
  "validation_fraction": 0.2,
  "treatment": "ads",
  "score_protocol": "<predeclared-training-and-cross-fitting-protocol>",
  "candidate_names": ["candidate-a", "candidate-b"]
}
```

The manifest candidate set must match the plan before validation is read.

## Validation JSONL

Each validation row contains the randomized record plus a score for **every** preregistered candidate:

```json
{
  "unit_id": "row-000001",
  "features": [0.1, 1.7, -0.4],
  "action": "ads",
  "outcome": 1.0,
  "action_propensities": {"ads": 0.5, "no_treatment": 0.5},
  "group_id": "user-17",
  "scores": {
    "candidate-a": 0.041,
    "candidate-b": 0.036
  }
}
```

Every validation row must expose the same candidate-name set. The runner evaluates the top-score treatment policy on randomized evidence and freezes the candidate with the strongest validation incremental value versus `NO_TREATMENT`.

## Holdout JSONL

The final holdout contains only the frozen winner's score and explicitly declares that winner:

```json
{
  "unit_id": "row-900001",
  "features": [0.3, 1.2, 0.5],
  "action": "no_treatment",
  "outcome": 0.0,
  "action_propensities": {"ads": 0.5, "no_treatment": 0.5},
  "group_id": "user-900",
  "selected_candidate": "candidate-a",
  "score": 0.028
}
```

A holdout row declaring another candidate fails closed. Validation/test unit identity overlap also fails closed.

## Fingerprint chain

For a preregistered targeting run (`growthevo.locked-targeting-run.v2`), the final artifact binds:

- experiment-plan fingerprint;
- realized export-manifest fingerprint;
- validation randomized rows **and all candidate score vectors**;
- final randomized rows and frozen winner scores;
- selected fraction/treatment protocol;
- code commit SHA;
- dataset source and score-protocol identifier.

Therefore changing a model prediction changes the evidence fingerprint even if the model name is unchanged.

## Backend neutrality

The locked runner evaluates scores; it intentionally does not require LightGBM, EconML, CausalML, causal forests, or neural uplift libraries in the core runtime. A high-performance external backend can participate by producing scores under a preregistered `score_protocol`.

This keeps the causal/evaluation contract stable while allowing benchmark candidates to improve over time.

## Promotion rule

Do not inspect final Criteo holdout uplift for several models and report the best one. A changed candidate set, model recipe, split, outcome, selected fraction, or dataset release is a new experiment plan. Current README performance should only be updated from a fresh preregistered locked artifact; historical pre-locked numbers remain legacy provenance.
