# Locked Randomized Targeting Run

`growthevo-locked-targeting` selects a targeting/CATE score model using randomized validation evidence and evaluates only the frozen winner on final holdout.

For new promotable Criteo-style evidence, use a **v2 preregistered plan** rather than an ad-hoc final-test model comparison. Version 1 remains supported so existing locked artifacts keep their original fingerprint and semantics.

## Locked execution order

```text
plan + realized manifest agreement
        ↓
train-only score generation already frozen
        ↓
open validation with every preregistered candidate score
        ↓
select candidate by randomized incremental value vs treat-none
        ↓
freeze winner
        ↓
generate/open only the winner's holdout score
        ↓
one final randomized holdout evaluation
```

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

`--experiment-plan-json` and `--export-manifest-json` must be supplied together. Plan/manifest/runtime disagreement fails before validation evidence is opened.

## Targeting experiment plan v2

`growthevo.targeting-experiment-plan.v2` freezes both evaluation and the statistically material upstream training boundary:

- benchmark, dataset and pinned source identity;
- outcome definition;
- deterministic split algorithm;
- **training fraction**;
- **validation fraction**; the remainder is final holdout;
- **split seed**;
- treatment arm;
- selected top fraction;
- **propensity protocol**;
- score-generation protocol identifier;
- **fingerprint of the complete candidate/model configuration**;
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

`training_fraction + validation_fraction` must be strictly below one. A v2 plan therefore cannot silently consume all data before the final holdout is defined.

The candidate-config fingerprint is separate from candidate names. Renaming nothing while changing tree count, learning rate, nuisance folds, random seeds, objective, or learner recipe is a **new model configuration** and must produce a different fingerprint before validation is opened.

## Propensity provenance

Randomized assignment does not justify inventing a propensity value that is absent from the public release. A protocol may use a documented design propensity when the exact design fact is available. Otherwise, a full benchmark can predeclare a pooled assignment share estimated **only from the training split**, freeze it, and then apply that frozen value to validation and holdout.

The latter is an empirical propensity protocol, not a claim about the unpublished experiment strata. Holdout inference is conditional on that independently estimated frozen propensity unless a separate procedure explicitly propagates propensity-estimation uncertainty.

## Realized targeting manifest v2

A v2 plan requires `growthevo.targeting-export.v2`. The manifest repeats the realized values of every upstream v2 field that can drift:

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

Any mismatch fails before validation scores are read.

## Version 1 compatibility

`growthevo.targeting-experiment-plan.v1` and `growthevo.targeting-export.v1` remain valid for already-audited externally generated score workflows. Their canonical payload and fingerprint do not gain v2 fields retroactively.

New full-data promotion work should use v2 because a candidate name plus a generic score-protocol string is not enough to prove train/validation isolation or freeze concrete model configuration.

## Validation evidence

Each validation row contains the randomized record plus a score for **every** preregistered candidate:

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

Every validation row must expose the same candidate-name set. The protocol evaluates the top-score treatment policy on randomized evidence and freezes the candidate with the strongest validation `incremental_value_vs_none`. Final holdout is not used for model selection.

## Final holdout

The holdout contains only the frozen winner's score and explicitly declares that winner:

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

A holdout row declaring another candidate fails closed. Validation/test unit identity overlap also fails closed.

## Frozen-policy uncertainty

For a selected top-k set `S`, only selected units differ from the treat-none comparator. The Horvitz-Thompson policy-minus-none term is

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

The population incremental value is

```math
\widehat\Delta
=
\frac{1}{n}\sum_{i=1}^{n}D_i,
```

with sample standard error

```math
\widehat{SE}(\widehat\Delta)
=
\sqrt{
\frac{1}{n(n-1)}
\sum_{i=1}^{n}
(D_i-\widehat\Delta)^2
}.
```

`infer_randomized_targeting` reports this uncertainty for an **already-frozen** score vector. It also reports selected-group incremental effect

```math
\widehat\Delta_{selected}
=
\frac{\widehat\Delta}{|S|/n},
```

and its correspondingly scaled standard error and normal interval.

This interval is appropriate for the frozen final policy contrast. It is not a confidence interval for the preceding model-selection search. The existing stratified bootstrap remains available for smaller studies; repeatedly reranking a multi-million-row dataset hundreds of times is not the default full-data path.

## Fingerprint chain

For a preregistered targeting run, the final artifact binds:

- experiment-plan fingerprint;
- realized export-manifest fingerprint;
- validation randomized rows **and all candidate score vectors**;
- final randomized rows and frozen winner scores;
- selected fraction/treatment protocol;
- code commit SHA;
- dataset source and score protocol.

Version 2 additionally makes the training split, propensity protocol and candidate configuration independently auditable before validation opens.

## Backend neutrality

The locked evaluation contract intentionally does not make LightGBM, EconML, causal forests, or neural uplift libraries core runtime dependencies. A high-performance backend participates by producing scores under a preregistered v2 score/model configuration.

For very large datasets such as full Criteo, a specialized vectorized exporter/runner may avoid materializing millions of Python JSON objects while preserving these same plan, fingerprint, validation-selection and single-holdout semantics.

## Promotion rule

Do not inspect final Criteo holdout uplift for several models and report the best one. A changed candidate set, model recipe, split, propensity protocol, outcome, selected fraction or dataset release is a new experiment plan. Current README performance should only be updated from a fresh preregistered locked artifact; historical pre-locked numbers remain legacy provenance.
