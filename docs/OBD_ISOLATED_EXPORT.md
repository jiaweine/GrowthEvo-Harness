# Open Bandit Dataset · GrowthEvo Locked OPE

GrowthEvo keeps Open Bandit tooling optional so the core runtime remains dependency-light. Install the research bridge with:

```bash
pip install -e '.[obd]'
```

The `obd` extra pins `sb-obp==0.5.10` on supported Python versions. OBP, scikit-learn, pandas, and NumPy are imported only by the research bridge. Full-data CI also uses a CPU-only PyTorch installation for a compact reproducible environment.

## Evidence levels

| Level | Data | Purpose | Repository role |
| --- | --- | --- | --- |
| **Integration evidence** | pinned small OBD from `sb-ai-lab/sb-obp` | verify API, data, Q-model, OPE, and evidence-chain compatibility | PR CI regression |
| **Research evidence** | full ZOZO Open Bandit Dataset | compare predeclared estimators under a locked protocol | accepted full-data OPE evidence |

The canonical dataset identity is the ZOZO Research Open Bandit Dataset release. Automated research execution uses a pinned ZOZO NEXT mirror revision while retaining canonical source provenance in the artifact.

## Current accepted full-data result

The accepted full OBD artifact is stored at:

`benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/`

| Metric | Locked result |
| --- | ---: |
| Random-policy evidence rows | **1,374,327** |
| BernoulliTS reference rows | **12,357,200** |
| Predeclared estimator configurations | **9** |
| Validation winner | **IPS** |
| Final estimate | **0.0045295435** |
| Final on-policy reference | `0.0049885087` |
| Final relative estimation error | `9.20045%` |
| Final support coverage | **1.0000** |
| Final ESS ratio | **0.16123** |

**Evidence commit:** `7d538cea9698b5f0a48c585eed85e3ae526e5af6`

---

## Pre-registered plans

The repository checks in explicit experiment plans:

- `benchmarks/ope/obd-small-all-random-to-bts.v1.json`
- `benchmarks/ope/obd-full-all-random-to-bts.v1.json`

Each plan fingerprints the benchmark identity before validation:

- dataset source;
- campaign;
- behavior and evaluation policies;
- reward definition;
- split strategy and validation fraction;
- Q model and cross-fit folds;
- BernoulliTS Monte Carlo replication count;
- random seed;
- support propensity floor;
- evidence gates;
- complete estimator/hyperparameter grid.

`growthevo-locked-ope` pairs `--experiment-plan-json` with `--export-manifest-json`. The plan captures intended protocol; the manifest captures the configuration that was actually materialized. Their fingerprints are persisted in the final evidence bundle.

## Target policy representation

The exporter implements the canonical `random` behavior policy and BernoulliTS evaluation policy direction. The ZOZOTOWN BernoulliTS policy is context-free, so the exporter stores the compact action distribution instead of repeating an equivalent distribution for every round.

For factual row `i`, logged action `a_i`, and slate position `p_i`:

```math
\pi_e(a_i\mid x_i,p_i)
=
\mathrm{action\_dist}[a_i,p_i].
```

The exporter validates probability mass at every observed position. CI also checks compact semantics against the equivalent tiled OBP representation.

## Compact cross-fitted Q terms

The research bridge preserves OBP `RegressionModel.fit` feature and position semantics inside each cross-fitting fold while retaining only the quantities required by GrowthEvo OPE.

For the factual action:

```math
\widehat q_i=\widehat Q_i(a_i,p_i).
```

For the target-policy expected reward:

```math
\widehat q_{\pi,i}
=
\sum_a
\pi_e(a\mid x_i,p_i)\widehat Q_i(a,p_i).
```

These become GrowthEvo's `baseline_q` and `target_q` fields for DM, DR, SWITCH-DR, and DR-OS.

Small-OBD CI compares compact logistic predictions with OBP `RegressionModel.fit_predict` output at `1e-12` numerical tolerance.

## Paired chronological evaluation

The locked OBD experiment uses paired validation and final windows across the two logged policies.

| Cohort | Purpose |
| --- | --- |
| Earlier random-policy rows | validation OPE evidence |
| Earlier BernoulliTS rows | validation on-policy reference |
| Later random-policy rows | final OPE evidence |
| Later BernoulliTS rows | final on-policy reference |

BTS timestamps are parsed as ISO-8601 UTC instants before splitting. The experiment definition is captured in the GrowthEvo plan and reproduced by the full-data runner.

## Evidence gate

Estimator ranking starts after the logged cohort satisfies the predeclared evidence criteria. Current OBD plans use:

- target-policy support coverage `>= 0.95`;
- effective sample ratio `>= 0.05`;
- positive supported importance mass.

The evidence gate is part of the experiment identity, so support criteria and estimator configuration remain frozen together.

## Small OBD CI

PR CI uses an external OBD snapshot pinned to:

```text
sb-ai-lab/sb-obp@1c6d14677ec6f06094a2f8886a1158bab99c571e
```

The job performs nine checks:

1. installs `.[obd]` on Python 3.12;
2. verifies compact logistic Q against OBP tensor predictions;
3. fetches the pinned small-OBD source;
4. exports `all/random` evidence for the BernoulliTS target policy with 2-fold logistic Q and `n_sim=500`;
5. validates the realized manifest against the pre-registered plan;
6. applies support and ESS gates;
7. selects the candidate estimator on validation reference evidence;
8. evaluates the frozen candidate on final holdout;
9. uploads the plan, manifest, candidate grid, and locked result.

This CI path keeps the entire real-data OPE integration contract under continuous regression coverage.

## Full OBD runner

Run the research-scale `all/random` to BernoulliTS protocol with:

```bash
pip install -e '.[obd]'
python scripts/run_obd_full_locked.py
```

Without `--data-root`, the runner materializes only the files required by the checked-in `all` campaign plan from the pinned mirror revision:

- `random/all/all.csv` for OPE evidence;
- `bts/all/all.csv` for the on-policy reference;
- `random/all/item_context.csv` for action context.

Before transfer, the runner checks available disk space. Materialized files are SHA256-hashed, and byte count, mirror revision, and canonical release identity are recorded in `source-provenance.json`.

For an existing local dataset:

```bash
python scripts/run_obd_full_locked.py \
  --data-root /path/to/open_bandit_dataset \
  --output-dir /path/to/locked-obd-result
```

The full plan fixes:

| Field | Value |
| --- | --- |
| Campaign | `all` |
| Behavior policy | `random` |
| Evaluation policy | `bts` |
| Reward | click |
| Validation fraction | `0.5` |
| Q model | logistic |
| Q cross-fit folds | `3` |
| BernoulliTS simulations | `100000` |
| Seed | `12345` |
| Estimator grid | finite predeclared candidate panel |
| Evidence gate | support and ESS thresholds from the plan |

The dedicated full-data workflow records the exact evidence commit and uploads `pip freeze` alongside the compact evidence bundle. Large source CSVs and generated row-level JSONL remain outside the persisted repository artifact.

## Locked result bundle

A `growthevo.locked-ope-run.v3` result records:

- validation scoreboard;
- selected estimator and hyperparameters;
- final holdout estimate, error, and uncertainty;
- ESS, support, and importance-weight diagnostics;
- code commit SHA;
- validation and holdout evidence fingerprints;
- experiment-plan fingerprint;
- realized export-manifest fingerprint;
- bound protocol fingerprint.

The full research bundle additionally records source-file SHA256 provenance and the exact Python environment.

## Candidate panel

The finite candidate grid can include:

- cross-fitted β*-IPS;
- Doubly Robust;
- IPS;
- SNIPS;
- SWITCH-DR thresholds;
- DR-OS shrinkage values;
- Meta-OPE / BLUE-style candidates.

The complete grid is fixed in the experiment plan before validation. The benchmark objective then determines the validation winner, which is frozen before final evaluation.

This design separates library-level estimator preference from benchmark-specific empirical selection: GrowthEvo can expose advanced estimators while still allowing the locked validation evidence to decide the final benchmark candidate.

## Evidence identity

A new promoted OBD result receives a new experiment identity whenever material source, split, Q protocol, target-policy simulation, evidence-gate, or candidate-grid choices change. This keeps historical accepted results stable and makes each new research comparison independently auditable.
