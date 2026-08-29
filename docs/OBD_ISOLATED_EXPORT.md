# Open Bandit Dataset → GrowthEvo Locked OPE

GrowthEvo keeps Open Bandit tooling **optional**. The default runtime remains dependency-free; real OBD work installs the maintained research bridge with:

```bash
pip install -e '.[obd]'
```

The `obd` extra pins the `sb-obp==0.5.10` distribution on supported Python versions. The exporter remains outside the core runtime and imports OBP, scikit-learn, pandas and NumPy only when executed. Full-data CI additionally installs a CPU-only PyTorch build so the research environment does not pull an unused CUDA stack.

## Evidence levels

GrowthEvo deliberately separates two OBD uses:

| Level | Data | Purpose | README performance claim? |
| --- | --- | --- | --- |
| Integration evidence | pinned small OBD from `sb-ai-lab/sb-obp` | prove API/data/Q/OPE pipeline compatibility | No |
| Research evidence | full ZOZO Open Bandit Dataset | estimator comparison and promotable real-world evidence | Only with a locked artifact |

The canonical full release is published by ZOZO Research. For automated execution, GrowthEvo uses the ZOZO NEXT mirror pinned to OBD 1.0 data revision `57a688e`, while retaining the canonical ZOZO Research release URL as the dataset identity.

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
- Q model and cross-fit folds;
- BernoulliTS Monte Carlo replication count;
- random seed;
- support propensity floor;
- evidence gates;
- complete estimator/hyperparameter grid.

`growthevo-locked-ope` accepts `--experiment-plan-json` together with `--export-manifest-json`. Plan/runtime/manifest disagreement fails **before validation JSONL is read**. The final artifact binds both the plan fingerprint and the realized export-manifest fingerprint.

## Target policy without the full round tensor

The exporter implements the canonical `random → BernoulliTS` direction and reconstructs the ZOZOTOWN BernoulliTS distribution through OBP. This production policy is context-free. OBP first computes one Monte Carlo action distribution and its historical batch helper repeats that same distribution over rounds. GrowthEvo therefore keeps the single `(n_actions, len_list)` distribution rather than materializing an equivalent `n_rounds` tile.

For factual row `i`, logged action `a_i`, and slate position `p_i`:

```math
\pi_e(a_i\mid x_i,p_i)
=
\mathrm{action\_dist}[a_i,p_i].
```

The exporter validates that target-policy mass sums to one at every observed position. CI also compares the compact path against the historical tiled semantics.

## Compact cross-fitted Q terms

The research path preserves OBP `RegressionModel.fit` feature and position semantics inside each K-fold split, but it does **not** retain the full `(n_rounds, n_actions, len_list)` Q tensor. On held-out rows it computes only the two quantities needed by GrowthEvo OPE.

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

These become GrowthEvo's `baseline_q` and `target_q` for DM/DR/SWITCH-DR/DR-OS. Small-OBD CI directly compares these compact logistic predictions with OBP `RegressionModel.fit_predict` tensor output at `1e-12` numerical tolerance. `--q-model zero` remains a debugging option only and is not admissible as DM/DR performance evidence.

## Paired chronological validation/holdout

The GrowthEvo protocol adds a locked model-selection layer to the official two-production-policy OPE idea:

- earlier random-policy rows → validation OPE evidence;
- earlier BTS rows → validation on-policy reference;
- later random-policy rows → final OPE evidence;
- later BTS rows → final on-policy reference.

BTS timestamps are parsed as ISO-8601 UTC instants before the GrowthEvo chronological split. The full release contains timestamps both with and without fractional seconds, so the parser explicitly accepts mixed ISO-8601 precision. This paired split is a **GrowthEvo experiment definition**, not a claim that historical OBP used the identical split or timestamp implementation.

## Evidence gate

Estimator error is ranked only after the OPE cohort passes the predeclared evidence gate. The checked-in OBD plans currently require:

- target-policy-mass support coverage `>= 0.95`;
- effective sample ratio `>= 0.05`;
- positive supported importance mass.

These are benchmark acceptance thresholds, not universal statistical constants. A failed validation or holdout gate is a failed reveal; the runner does not permit swapping in another cohort after inspecting diagnostics.

## Small OBD CI

PR CI uses a real external dataset pinned exactly to:

```text
sb-ai-lab/sb-obp@1c6d14677ec6f06094a2f8886a1158bab99c571e
```

The job:

1. installs `.[obd]` on Python 3.12;
2. verifies compact logistic Q against OBP tensor predictions;
3. fetches that exact small-OBD commit;
4. exports the `all/random → BTS` evidence with 2-fold logistic Q and `n_sim=500`;
5. validates the realized manifest against `obd-small-all-random-to-bts.v1.json`;
6. applies the evidence gate;
7. selects an estimator only on validation reference evidence;
8. reveals the final holdout once;
9. uploads the plan, manifest, candidate grid and locked result.

This is real-data integration evidence. It is intentionally not promoted as the full-data OPE performance result.

## Full OBD one-command runner

For the research-scale `all/random → BTS` plan:

```bash
pip install -e '.[obd]'
python scripts/run_obd_full_locked.py
```

With no `--data-root`, the runner does **not** download and extract the 11.7 GB aggregate archive. It fetches only the three files required by the checked-in `all` campaign plan from the pinned ZOZO NEXT OBD 1.0 revision:

- `random/all/all.csv` — OPE evidence;
- `bts/all/all.csv` — factual on-policy reference;
- `random/all/item_context.csv` — action context used by OBP preprocessing.

Before transfer, the runner checks advertised file sizes against free disk with a 2 GiB reserve. Each materialized file is SHA256-hashed and its byte count, pinned mirror revision and canonical release identity are written to `source-provenance.json`.

If the full dataset is already available locally:

```bash
python scripts/run_obd_full_locked.py \
  --data-root /path/to/open_bandit_dataset \
  --output-dir /path/to/locked-obd-result
```

The full plan fixes:

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

The dedicated full-data workflow checks out the exact evidence commit rather than GitHub's temporary PR merge ref, uses `set -o pipefail`, verifies the artifact commit SHA, and uploads `pip freeze` beside the compact evidence bundle. Large source CSVs and generated JSONL evidence are not uploaded as artifacts.

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

The accompanying research evidence bundle adds source-file SHA256 provenance and the exact installed Python distributions. A number without this provenance is not current GrowthEvo real-world evidence.

## Candidate policy

The finite candidate grid includes cross-fitted β*-IPS, DR, IPS, SNIPS, SWITCH-DR thresholds, DR-OS shrinkage values, and the current Meta-OPE diagnostic candidate. The grid is fixed before validation. Adding/removing an estimator or tuning value requires a new plan fingerprint and therefore a new benchmark protocol; it cannot be changed after observing final holdout performance.

The validation winner is selected by evidence, not by novelty. A newer estimator is not promoted merely because it is newer; if a simpler candidate wins the frozen validation criterion, that simpler candidate is the one revealed on final holdout.

## Promotion rule

README headline performance may be updated only from a **fresh full-data preregistered artifact** whose code commit is a real repository commit and whose validation/holdout fingerprints differ. Small OBD CI, historical pre-locked numbers, synthetic tests, temporary PR merge SHAs, or a manually selected final-test estimator are not substitutes.
