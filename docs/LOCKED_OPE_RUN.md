# Locked OPE Run

This command is the executable path for promoting an Open Bandit-style OPE result. It deliberately separates estimator selection from final holdout evaluation.

## Command

After installing the package:

```bash
growthevo-locked-ope \
  --tuning-jsonl validation.jsonl \
  --test-jsonl holdout.jsonl \
  --candidates-json ope_candidates.json \
  --tuning-reference 0.01234 \
  --test-reference 0.01210 \
  --benchmark open-bandit-ope \
  --dataset obd-all-random-vs-bts \
  --commit-sha "$(git rev-parse HEAD)" \
  --output benchmark-result.json
```

The implementation reads the candidate list and validation evidence first, freezes the winning estimator, and only then opens `holdout.jsonl`.

The reference values must come from a legitimate validation/test ground-truth or on-policy reference protocol. Open Bandit Dataset is useful here because multiple production logging policies were run on the same platform, enabling real-world OPE estimator evaluation against policy values measured from online logs.

## OPE JSONL schema

Each line is one logged evaluation record:

```json
{
  "reward": 1.0,
  "behavior_propensity": 0.05,
  "target_action_probability": 0.08,
  "baseline_q": 0.031,
  "target_q": 0.034,
  "record_id": "campaign=all/day=3/row=481920",
  "cluster_id": ["day", 3]
}
```

Required fields:

- `reward`: observed reward for the logged action;
- `behavior_propensity`: logged probability of that action under the behavior policy;
- `target_action_probability`: probability assigned to that same logged action by the target policy;
- `baseline_q`: estimated reward for the logged action used by DR-style correction;
- `target_q`: target-policy expected Q term used by DM/DR;
- `record_id`: stable, unique, source-order-invariant identity.

`cluster_id` is optional. Supply it only when the experiment has a defensible repeated-unit/block definition. JSON arrays are converted to immutable tuple identities. Do not invent clusters merely to obtain a different standard error.

For paper-facing runs, nuisance/Q predictions should be produced by a training/cross-fitting protocol that never learns from the final holdout outcomes it predicts.

## Candidate schema

`ope_candidates.json` is a non-empty JSON array. Every candidate and every tuning parameter must be declared before final holdout evaluation.

```json
[
  {"name": "beta-cf5", "estimator": "beta_ips", "beta_folds": 5},
  {"name": "dr", "estimator": "doubly_robust"},
  {"name": "ips", "estimator": "ips"},
  {"name": "snips", "estimator": "self_normalized_ips"},
  {"name": "switch-10", "estimator": "switch_dr", "switch_threshold": 10.0},
  {"name": "dros-10", "estimator": "dr_os", "dr_os_lambda": 10.0},
  {"name": "meta-blue", "estimator": "meta_blue"}
]
```

Supported estimator names are:

- `direct_method`
- `ips`
- `self_normalized_ips`
- `doubly_robust`
- `switch_dr`
- `dr_os`
- `beta_ips`
- `meta_blue`

`switch_threshold` is valid only for `switch_dr`; `dr_os_lambda` is valid only for `dr_os`. β cross-fit folds are fixed by `beta_folds`.

A large hyperparameter grid can itself overfit validation. Candidate multiplicity should therefore be justified and fixed in the experiment protocol rather than expanded after inspecting results.

## Output

The output JSON contains two components:

1. `validation_scores`: all pre-declared candidates evaluated against the validation reference;
2. `artifact`: the single frozen winner evaluated on the final holdout.

The artifact includes:

- benchmark and dataset identity;
- commit SHA;
- selected candidate;
- protocol fingerprint;
- tuning-evidence fingerprint;
- test-evidence fingerprint;
- final estimate/error/SE;
- ESS ratio, support coverage and maximum importance weight.

OPE evidence fingerprints include rewards, logged propensities, target-policy probabilities, Q predictions, stable record IDs and cluster IDs. Changing any of these changes the fingerprint.

## Promotion rule

Do **not** run a second candidate set against the same final holdout and replace the reported result because it looks better. If the method or hyperparameter grid changes after the holdout is revealed, create a new experimental claim with a new untouched holdout/cohort or clearly label it exploratory rather than confirmation evidence.

The in-memory one-reveal guard is a workflow safety mechanism, not a cryptographic claim. Reproducibility ultimately comes from the pre-declared protocol, immutable data/model evidence, fingerprints, code SHA and publication of the full validation scoreboard alongside the single final-test winner.
