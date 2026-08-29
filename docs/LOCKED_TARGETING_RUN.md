# Locked Randomized Targeting Run

`growthevo-locked-targeting` is the executable promotion path for Criteo-style randomized targeting comparisons.

The goal is to answer a narrow question without final-test model shopping:

> Given several pre-trained uplift/CATE scoring models, which model produces the best randomized targeting policy on validation, and how does that **frozen winner** perform on an untouched holdout?

## Command

```bash
growthevo-locked-targeting \
  --tuning-jsonl validation-targeting.jsonl \
  --test-jsonl holdout-targeting.jsonl \
  --selected-fraction 0.10 \
  --treatment ads \
  --benchmark criteo-targeting \
  --dataset criteo-uplift-v2 \
  --commit-sha "$(git rev-parse HEAD)" \
  --output benchmark-result.json
```

The command reads all candidate scores from validation, selects the winner by randomized `incremental_value_vs_none`, freezes that candidate name, and only then opens the holdout file.

## Validation JSONL

Each row contains one randomized treatment record plus scores from the complete pre-declared candidate set:

```json
{
  "unit_id": "row-000001",
  "features": [0.31, -1.42, 0.08],
  "action": "ads",
  "outcome": 1.0,
  "action_propensities": {
    "ads": 0.5,
    "no_treatment": 0.5
  },
  "group_id": "optional-user-or-block",
  "scores": {
    "dr-ridge": 0.034,
    "causal-forest-v3": 0.051,
    "neural-uplift-v2": 0.047
  }
}
```

Every validation row must contain exactly the same candidate-name set. Candidate multiplicity is itself a tuning choice and should be fixed before inspecting final holdout performance.

The logged assignment probabilities must represent the experiment's defensible treatment mechanism. Do not substitute post-treatment exposure for assignment.

## Holdout JSONL

The holdout deliberately does **not** accept a map of every model's scores. Each row carries only the score of the frozen validation winner and declares its name:

```json
{
  "unit_id": "holdout-row-000001",
  "features": [0.28, -1.37, 0.11],
  "action": "no_treatment",
  "outcome": 0.0,
  "action_propensities": {
    "ads": 0.5,
    "no_treatment": 0.5
  },
  "group_id": "optional-user-or-block",
  "selected_candidate": "causal-forest-v3",
  "score": 0.049
}
```

If `selected_candidate` differs from the winner selected on validation, execution fails before the randomized holdout metric is produced.

## Data/model isolation

The underlying `LockedTargetingProtocol` additionally enforces:

- stable, unique `unit_id` values;
- zero validation/holdout identity overlap, including partial overlap;
- evidence fingerprints that bind randomized rows and model scores;
- one holdout reveal per protocol object;
- artifact binding to commit SHA, protocol fingerprint, validation evidence and holdout evidence.

A different model score vector on the same rows produces a different evidence fingerprint.

## Output

The JSON bundle contains:

- the complete validation scoreboard for all candidates;
- one final `LockedBenchmarkArtifact` for the frozen winner;
- randomized policy value;
- treat-none and treat-all references;
- incremental value versus no treatment;
- selected fraction;
- code/protocol/evidence fingerprints.

## Important limitation

This runner evaluates already-produced candidate scores. It does not train the CATE models itself. Training/nuisance fitting must respect the outer train/validation/test split: the final holdout outcomes must not be used to fit a model whose scores are then evaluated on that holdout.

The runner prevents a common evaluation failure — choosing the best model on final randomized uplift — but it cannot repair upstream leakage that occurred while producing the score files.
