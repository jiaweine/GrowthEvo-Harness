# Locked Randomized Targeting Run

`growthevo-locked-targeting` selects a targeting/CATE score model using randomized validation evidence and evaluates the frozen winner on an independent final holdout.

For new Criteo-style evidence, the v2 preregistered plan captures both the evaluation protocol and the statistically material upstream model-generation configuration. Version 1 remains available for compatibility with already-audited artifacts.

## Execution contract

| Stage | Action |
| ---: | --- |
| **1** | Verify experiment plan, runtime configuration, and realized manifest agreement |
| **2** | Load the train-generated validation scores for every preregistered candidate |
| **3** | Evaluate candidates by randomized incremental value versus treat-none |
| **4** | Select and freeze the validation winner |
| **5** | Produce or load the frozen winner's holdout score |
| **6** | Evaluate the frozen policy once on final randomized holdout |
| **7** | Persist the locked artifact and fingerprint chain |

The generic CLI consumes already-materialized validation and holdout scores:

```bash
growthevo-locked-targeting \
  --tuning-jsonl validation.jsonl \
  --test-jsonl holdout.jsonl \
  --selected-fraction 0.10 \
  --treatment ads \
  --benchmark criteo-uplift-targeting \
  --dataset criteo-uplift-v2.1 \
  --commit-sha "$(git rev-parse HEAD)" \
  --experiment-plan-json targeting-plan.json \
  --export-manifest-json targeting-export-manifest.json \
  --output targeting-result.json
```

`--experiment-plan-json` and `--export-manifest-json` are supplied together so intended configuration and realized score generation can be checked before validation evidence is evaluated.

## Targeting experiment plan v2

`growthevo.targeting-experiment-plan.v2` freezes the training and evaluation choices that define one benchmark identity:

- benchmark and dataset identity;
- pinned source identity;
- outcome definition;
- deterministic split algorithm;
- training fraction;
- validation fraction;
- split seed;
- treatment arm;
- selected top fraction;
- propensity protocol;
- score-generation protocol identifier;
- fingerprint of the complete candidate/model configuration;
- complete candidate-name set.

Example:

```json
{
  "schema_version": "growthevo.targeting-experiment-plan.v2",
  "benchmark": "criteo-uplift-targeting-full-evidence",
  "dataset": "criteo-uplift-v2.1",
  "dataset_source": "criteo-hf:<pinned-commit>:sha256:<file-digest>",
  "outcome_definition": "visit",
  "split_strategy": "stable_hash_source_row_v1",
  "training_fraction": 0.50,
  "validation_fraction": 0.25,
  "split_seed": 20260830,
  "treatment": "ads",
  "selected_fraction": 0.10,
  "propensity_protocol": "pooled-training-assignment-share-v1",
  "score_protocol": "fixed-lightgbm-cate-candidates-v1",
  "candidate_config_fingerprint": "0123456789abcdef0123456789abcdef01234567",
  "candidate_names": ["s-lgbm", "t-lgbm", "x-lgbm", "r-lgbm", "dr-lgbm"]
}
```

`training_fraction + validation_fraction` remains below one, reserving the remaining rows for the final holdout.

The candidate-config fingerprint is separate from the candidate names. Tree count, learning rate, nuisance folds, random seeds, objective, and learner recipe are therefore captured as part of the experiment identity rather than hidden behind a model label.

## Propensity provenance

The targeting protocol supports a documented design propensity when that value is available from the randomized experiment. It also supports a predeclared empirical protocol that estimates the pooled assignment share from the training split and freezes that value before validation and holdout evaluation.

This keeps propensity provenance explicit and separates training-time estimation from final evaluation.

## Realized targeting manifest v2

A v2 plan is paired with `growthevo.targeting-export.v2`. The manifest records the realized values of the upstream configuration:

```json
{
  "schema_version": "growthevo.targeting-export.v2",
  "dataset_source": "criteo-hf:<pinned-commit>:sha256:<file-digest>",
  "outcome_definition": "visit",
  "split_strategy": "stable_hash_source_row_v1",
  "training_fraction": 0.50,
  "validation_fraction": 0.25,
  "split_seed": 20260830,
  "treatment": "ads",
  "propensity_protocol": "pooled-training-assignment-share-v1",
  "score_protocol": "fixed-lightgbm-cate-candidates-v1",
  "candidate_config_fingerprint": "0123456789abcdef0123456789abcdef01234567",
  "candidate_names": ["s-lgbm", "t-lgbm", "x-lgbm", "r-lgbm", "dr-lgbm"]
}
```

The runner checks the plan and manifest before validation scoring. This binds declared intent to the configuration that actually produced the candidate scores.

## Version 1 compatibility

`growthevo.targeting-experiment-plan.v1` and `growthevo.targeting-export.v1` remain valid for existing audited externally generated score workflows. Their canonical payloads and fingerprints remain stable.

New full-data targeting work uses v2 so train/validation separation and concrete model configuration are independently auditable.

## Validation evidence

Each validation row carries the randomized record and one score per preregistered candidate:

```json
{
  "unit_id": "row-000001",
  "features": [0.1, 1.7, -0.4],
  "action": "ads",
  "outcome": 1.0,
  "action_propensities": {"ads": 0.85, "no_treatment": 0.15},
  "scores": {
    "s-lgbm": 0.041,
    "dr-lgbm": 0.036
  }
}
```

Every validation row exposes the same candidate-name set. The protocol evaluates each candidate's top-score treatment policy on randomized evidence and freezes the candidate with the strongest validation `incremental_value_vs_none`.

## Final holdout

The final holdout contains the frozen winner's score together with the selected candidate identity:

```json
{
  "unit_id": "row-900001",
  "features": [0.3, 1.2, 0.5],
  "action": "no_treatment",
  "outcome": 0.0,
  "action_propensities": {"ads": 0.85, "no_treatment": 0.15},
  "selected_candidate": "s-lgbm",
  "score": 0.028
}
```

Stable row identities keep validation and holdout cohorts disjoint, and the selected-candidate field preserves the frozen model identity through final evaluation.

## Frozen-policy uncertainty

For selected top-k set `S`, the Horvitz-Thompson policy-minus-none contribution is:

```math
D_i
=
\mathbf{1}\{i\in S\}
\left[
\frac{\mathbf{1}\{A_i=t\}Y_i}{e_t}
-
\frac{\mathbf{1}\{A_i=0\}Y_i}{e_0}
\right].
```

The population incremental value is:

```math
\widehat\Delta
=
\frac{1}{n}\sum_{i=1}^{n}D_i.
```

Its sample standard error is:

```math
\widehat{SE}(\widehat\Delta)
=
\sqrt{
\frac{1}{n(n-1)}
\sum_{i=1}^{n}
(D_i-\widehat\Delta)^2
}.
```

The selected-group effect is:

```math
\widehat\Delta_{selected}
=
\frac{\widehat\Delta}{|S|/n}.
```

`infer_randomized_targeting` reports population and selected-group estimates, standard errors, and intervals for the already-frozen policy score vector. Stratified bootstrap utilities remain available for smaller studies.

## Fingerprint chain

The final targeting artifact binds:

- experiment-plan fingerprint;
- candidate-configuration fingerprint;
- realized export-manifest fingerprint;
- validation randomized rows and complete candidate score vectors;
- final randomized rows and frozen winner score;
- selected-fraction and treatment protocol;
- dataset source and score protocol;
- code commit SHA.

Version 2 additionally binds the training split and propensity protocol as explicit upstream experiment fields.

## Backend neutrality

The locked targeting contract is independent of a specific modeling library. LightGBM, EconML, causal forests, neural uplift, or another backend can participate by producing scores under a preregistered model configuration.

For research-scale datasets, specialized vectorized runners can preserve the same plan, fingerprint, validation-selection, and final-holdout semantics without materializing millions of Python JSON objects.

## Current Criteo evidence

The repository's accepted full Criteo Uplift v2.1 artifact uses this locked selection philosophy:

| Metric | Result |
| --- | ---: |
| Source rows | **13,979,592** |
| Predeclared candidates | **5** |
| Validation winner | **S-Learner** |
| Population incremental visit | **+0.93791 pp** |
| Selected top-10% incremental visit | **+9.37910 pp** |

Evidence directory:

`benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/`

A new headline experiment receives its own plan and fingerprint identity whenever a material source, split, model configuration, propensity protocol, outcome, or targeting objective changes.
