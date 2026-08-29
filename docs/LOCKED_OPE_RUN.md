# Locked OPE Run

`growthevo-locked-ope` is the executable promotion path for Open Bandit-style OPE. It enforces three layers in order:

1. **pre-registration** — upstream data/Q/policy/candidate/gate settings must match a checked plan and realized export manifest;
2. **evidence eligibility** — validation and final OPE cohorts must pass predeclared support/ESS gates;
3. **locked selection** — choose on validation, freeze one estimator, then open final holdout once.

## Preregistered command

```bash
growthevo-locked-ope \
  --tuning-jsonl validation.jsonl \
  --test-jsonl holdout.jsonl \
  --candidates-json ope_candidates.json \
  --tuning-reference 0.01234 \
  --test-reference 0.01210 \
  --benchmark open-bandit-ope-small-evidence \
  --dataset obd-small-all-random-to-bts \
  --commit-sha "$(git rev-parse HEAD)" \
  --support-propensity-floor 0.001 \
  --min-support-coverage 0.95 \
  --min-effective-sample-ratio 0.05 \
  --experiment-plan-json benchmarks/ope/obd-small-all-random-to-bts.v1.json \
  --export-manifest-json export_manifest.json \
  --output benchmark-result.json
```

`--experiment-plan-json` and `--export-manifest-json` are optional only for exploratory/backwards-compatible runs. A promotable real-world result should supply both.

Plan/runtime/manifest agreement is checked **before `validation.jsonl` is opened**.

## Pre-registered OPE plan

`growthevo.ope-experiment-plan.v1` freezes:

- benchmark and dataset name;
- immutable dataset/source identity;
- campaign and behavior/evaluation policies;
- reward definition;
- split strategy and validation fraction;
- Q model and cross-fit folds;
- target-policy Monte Carlo replication count;
- seed;
- support propensity floor;
- evidence gate;
- complete estimator/hyperparameter grid.

Unknown plan/candidate fields and JSON type confusion fail closed. For example, JSON boolean `true` is not accepted as integer `1` for `q_folds`.

## Realized export manifest

The exporter records what was actually generated. For OBD, the current `growthevo.obd-export.v2` manifest includes dataset source, policy direction, reward, split, Q settings, simulation count and seed. The runner verifies those fields against the pre-registered plan and hashes the full manifest into the final evidence bundle.

A plan describes **intent**; the manifest describes **realization**. Both are retained.

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

`record_id` must be a stable non-empty string. `cluster_id` is optional and should only represent a defensible repeated-unit/block definition. Q predictions for paper-facing runs must be generated without holdout leakage.

## Candidate schema

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

Supported estimator names are `direct_method`, `ips`, `self_normalized_ips`, `doubly_robust`, `switch_dr`, `dr_os`, `beta_ips`, and `meta_blue`.

A large grid can overfit validation. Changing the grid after validation/final inspection creates a new protocol fingerprint and is not the same experiment.

## Evidence gate

The executable runner requires positive supported importance mass. Optional minimum support coverage and ESS ratio are predeclared through the plan/CLI. The current OBD plans use support `>= 0.95` and ESS ratio `>= 0.05`.

Gate order matters: a numerically accurate-looking estimator cannot win when the logged cohort itself lacks admissible OPE evidence.

## Output v3

A preregistered run emits `growthevo.locked-ope-run.v3` with:

- `validation_scores` for the complete predeclared grid;
- `evidence_gate` configuration;
- `experiment_plan.plan` and plan fingerprint;
- realized export-manifest fingerprint;
- final `artifact` for one frozen candidate.

The artifact binds:

- code commit SHA;
- bound protocol fingerprint;
- validation evidence fingerprint;
- holdout evidence fingerprint;
- experiment-plan fingerprint;
- export-manifest fingerprint;
- dataset source;
- final estimate/error/SE;
- ESS/support/importance-weight diagnostics.

## Promotion rule

Do not run another candidate grid against the same final holdout and replace the result. A changed estimator family, Q protocol, data source, split, seed, evidence gate or hyperparameter grid is a new experiment and receives a new plan/protocol fingerprint.

For the official OBD workflows, see `docs/OBD_ISOLATED_EXPORT.md` and `scripts/run_obd_full_locked.py`.
