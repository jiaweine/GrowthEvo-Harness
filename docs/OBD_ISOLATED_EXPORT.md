# Open Bandit Dataset → GrowthEvo Locked OPE

GrowthEvo keeps Open Bandit tooling **optional**. The default runtime remains dependency-free; real OBD work installs the maintained research bridge with:

```bash
pip install -e '.[obd]'
```

The `obd` extra pins `sb-obp==0.5.10` on supported Python versions. The exporter remains outside the core runtime and imports `obp`, sklearn and numpy only when executed.

## Evidence levels

GrowthEvo deliberately separates two OBD uses:

| Level | Data | Purpose | README performance claim? |
| --- | --- | --- | --- |
| Integration evidence | pinned small OBD from `sb-ai-lab/sb-obp` | prove API/data/Q/OPE pipeline compatibility | No |
| Research evidence | official full ZOZO Open Bandit Dataset (~26M impressions) | estimator comparison and promotable real-world evidence | Only with a locked artifact |

The official project recommends the small data for examples and the full release for research. The full release is published by ZOZO Research at `https://research.zozo.com/data_release/open_bandit_dataset.zip`.

## Pre-registered plans

A real OBD result is not accepted from command-line arguments alone. The repository checks in immutable experiment plans:

- `benchmarks/ope/obd-small-all-random-to-bts.v1.json`
- `benchmarks/ope/obd-full-all-random-to-bts.v1.json`

Each plan fingerprints, before validation is opened:

- benchmark and dataset identity;
- dataset source;
- campaign;
- behavior/evaluation policy direction;
- reward definition;
- split strategy and validation fraction;
- Q backend and cross-fit folds;
- BernoulliTS Monte Carlo replication count;
- random seed;
- support propensity floor;
- evidence gates;
- complete estimator/hyperparameter grid.

`growthevo-locked-ope` accepts `--experiment-plan-json` together with `--export-manifest-json`. Plan/runtime/manifest disagreement fails **before validation JSONL is read**. The final artifact binds both the plan fingerprint and the realized export-manifest fingerprint.

## Target policy

The exporter implements the canonical `random → BernoulliTS` direction and reconstructs the ZOZOTOWN BernoulliTS action distribution through OBP.

For factual row `i`, logged action `a_i`, and slate position `p_i`:

```math
\pi_e(a_i\mid x_i,p_i)
=
\mathrm{action\_dist}[i,a_i,p_i].
```

The exporter validates that target-policy mass sums to one at every factual row/position.

## Cross-fitted Q terms

The research path uses logistic `RegressionModel.fit_predict(..., n_folds=K)` independently inside validation and holdout windows. The OBP slate width is passed explicitly; the implementation does not rely on the regression model's single-position default.

For the factual action:

```math
\widehat q_i
=
\widehat Q_i(a_i,p_i).
```

For the target-policy expected reward:

```math
\widehat q_{\pi,i}
=
\sum_a
\pi_e(a\mid x_i,p_i)\widehat Q_i(a,p_i).
```

These become GrowthEvo's `baseline_q` and `target_q` for DM/DR/SWITCH-DR/DR-OS. `--q-model zero` remains a debugging option only and is not admissible as DM/DR performance evidence.

## Paired chronological validation/holdout

The GrowthEvo protocol adds a locked model-selection layer to the official two-production-policy OPE idea:

- earlier random-policy rows → validation OPE evidence;
- earlier BTS rows → validation on-policy reference;
- later random-policy rows → final OPE evidence;
- later BTS rows → final on-policy reference.

This paired chronological split is a GrowthEvo experiment definition, not a claim that the historical OBP benchmark used the exact same split.

## Evidence gate

Estimator error is ranked only after the OPE cohort passes the predeclared evidence gate. The checked-in OBD plans currently require:

- target-policy-mass support coverage `>= 0.95`;
- effective sample ratio `>= 0.05`;
- positive supported importance mass.

These are benchmark acceptance thresholds, not universal statistical constants. A failed validation or holdout gate is a failed reveal; the runner does not permit swapping in another cohort after inspecting diagnostics.

## Small OBD CI

PR CI uses a real external dataset, but pins the source exactly:

```text
sb-ai-lab/sb-obp@1c6d14677ec6f06094a2f8886a1158bab99c571e
```

The job:

1. installs `.[obd]` on Python 3.12;
2. fetches that exact commit;
3. exports the `all/random → BTS` small OBD with 2-fold logistic Q and `n_sim=500`;
4. validates the realized manifest against `obd-small-all-random-to-bts.v1.json`;
5. applies the evidence gate;
6. selects an estimator only on validation reference evidence;
7. reveals the final holdout once;
8. uploads the plan, manifest, candidate grid and locked result.

This is real-data integration evidence. It is intentionally not promoted as the full-data OPE performance result.

## Full OBD one-command runner

For the official research release:

```bash
pip install -e '.[obd]'
python scripts/run_obd_full_locked.py
```

With no `--data-root`, the runner downloads the official ZOZO archive, extracts it under `.benchmark-data/`, finds the OBD root, and executes the checked-in full plan. If the dataset is already available:

```bash
python scripts/run_obd_full_locked.py \
  --data-root /path/to/open_bandit_dataset \
  --output-dir /path/to/locked-obd-result
```

The full plan currently fixes:

- campaign: `all`;
- behavior policy: `random`;
- evaluation policy: `bts`;
- reward: click;
- validation fraction: `0.5`;
- Q model: logistic;
- Q cross-fit folds: `3`;
- BernoulliTS simulations: `100000`;
- seed: `12345`;
- the complete finite OPE candidate grid;
- support and ESS gates.

When the official archive is downloaded by the runner, its SHA256 is written to `source-provenance.json`. Generated data and benchmark-result directories are gitignored.

## Locked result bundle

A preregistered OPE result (`growthevo.locked-ope-run.v3`) includes:

- validation scoreboard;
- selected estimator/hyperparameters;
- final holdout estimate/error/uncertainty;
- ESS/support/importance-weight diagnostics;
- code commit SHA;
- validation and holdout evidence fingerprints;
- experiment-plan fingerprint;
- realized export-manifest fingerprint;
- bound protocol fingerprint.

A number without that provenance is not current GrowthEvo real-world evidence.

## Candidate policy

The finite candidate grid includes cross-fitted β*-IPS, DR, IPS, SNIPS, SWITCH-DR thresholds, DR-OS shrinkage values, and the current Meta-OPE diagnostic candidate. The grid is fixed before validation. Adding/removing an estimator or tuning value requires a new plan fingerprint and therefore a new benchmark protocol; it cannot be changed after observing final holdout performance.

## Promotion rule

README headline performance may be updated only from a **fresh full-data preregistered artifact**. Small OBD CI, historical pre-locked numbers, synthetic tests, or a manually selected final-test estimator are not substitutes.
