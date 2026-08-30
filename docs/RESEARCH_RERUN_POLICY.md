# Research Evidence Rerun Policy

Full-data real-world workflows are intentionally **manual-only** after a locked result has been accepted and persisted.

The repository currently has promoted locked evidence for:

- Criteo Uplift v2.1 targeting;
- the full Open Bandit Dataset OPE benchmark.

Those accepted artifacts are immutable historical evidence. Ordinary pull requests must not automatically rerun them or reopen their final holdouts.

## Why the full workflows are manual-only

A final holdout is not another validation set. Repeatedly running all candidates, changing a model after seeing final metrics, or automatically re-opening the same holdout on unrelated pull requests would weaken the selection protocol.

Therefore:

- `.github/workflows/full-criteo-pr-validation.yml` is triggered only by `workflow_dispatch`;
- `.github/workflows/full-obd-pr-validation.yml` is triggered only by `workflow_dispatch`;
- each dispatch requires a non-empty `experiment_reason`;
- accepted full-data workflows do not run automatically for ordinary PRs;
- ordinary PR CI instead runs unit/regression tests, package-build/install checks, persisted-evidence integrity checks, and the pinned small-OBD integration benchmark.

## Development validation exhaustion

Validation evidence can also be overused. Repeatedly proposing new methods after observing the same validation reference creates adaptive overfitting even if the final holdout remains untouched.

The small-OBD cohort described by `benchmarks/ope/obd-small-all-random-to-bts.v1.json` is therefore marked **exhausted for promotion research** in `benchmarks/ope/development/obd-small-all-random-to-bts.v1.json`.

It may continue to serve as a regression/integration fixture and may reproduce an already recorded attempt. It must not justify promotion of a newly proposed estimator, Q backend, hyperparameter choice, or candidate grid. Future empirical OPE promotion research requires a fresh preregistered development identity before its validation evidence is opened. See `docs/OPE_DEVELOPMENT_GOVERNANCE.md`.

Development comparisons should recompute their baseline inside the same run. Tiny floating-point differences across hosted hardware are not evidence that a method improved and must not be converted into a rerun-until-winning process.

## When a manual full-data run is admissible

A manual run is appropriate for one of two purposes.

### 1. Replication of an accepted experiment

A replication may rerun the exact frozen source, plan, candidate configuration, split, seeds, and selection contract to test reproducibility.

A replication does **not** replace the accepted result merely because its numeric output differs slightly. Any material discrepancy must be investigated and documented before promotion status changes.

### 2. A genuinely new preregistered experiment

Changing any material upstream choice creates a new experiment identity, including changes to:

- dataset source or release;
- outcome/reward definition;
- train/validation/holdout split or seed;
- propensity or Q-model protocol;
- candidate set or candidate hyperparameters;
- support/evidence gates;
- target-policy simulation protocol;
- selection objective.

The new experiment must receive a new plan/fingerprint and a new evidence directory. The previous final holdout result must not be used as a tuning signal for the new candidate set.

## Promotion rule

A new real-world result may replace or supplement a README headline only after it has:

1. a preregistered plan;
2. a realized manifest matching that plan;
3. validation-only candidate selection;
4. a frozen winner;
5. exactly one final holdout evaluation for that winner;
6. explicit uncertainty/support diagnostics required by the protocol;
7. exact code/data/environment provenance;
8. a persisted compact evidence bundle with fingerprints/digests;
9. passing repository integrity tests.

The accepted evidence directories are continuously checked by `tests/test_persisted_evidence.py`. The workflow trigger contract is continuously checked by `tests/test_research_workflow_policy.py`.
