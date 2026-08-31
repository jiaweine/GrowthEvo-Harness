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
- the dispatched commit must already belong to reviewed `main` history before real benchmark data may be accessed;
- each admitted dispatch persists its reason, ref, commit SHA, workflow identity, actor, triggering actor, run ID/attempt, and the contemporaneous `origin/main` SHA in `dispatch-provenance.json`;
- accepted full-data workflows do not run automatically for ordinary PRs;
- ordinary PR CI instead runs unit/regression tests, package-build/install checks, persisted-evidence integrity checks, and the pinned small-OBD integration benchmark.

The main-history rule intentionally allows an older commit that is an ancestor of current `main`, so an accepted historical state can be replicated without requiring the repository to move backward. A feature-branch commit that has not entered `main` is rejected. This code-level guard prevents accidental use of unreviewed research code; repository-level rulesets or protected environments remain the stronger control against an actor who deliberately edits or bypasses the workflow guard itself.

## Development validation exhaustion

Validation evidence can also be overused. Repeatedly proposing new methods after observing the same validation reference creates adaptive overfitting even if the final holdout remains untouched.

The small-OBD cohort described by `benchmarks/ope/obd-small-all-random-to-bts.v1.json` is therefore marked **exhausted for promotion research** in `benchmarks/ope/development/obd-small-all-random-to-bts.v1.json`.

It may continue to serve as a regression/integration fixture and may reproduce an already recorded attempt. It must not justify promotion of a newly proposed estimator, Q backend, hyperparameter choice, or candidate grid. Future empirical OPE promotion research requires a fresh preregistered development identity before its validation evidence is opened. See `docs/OPE_DEVELOPMENT_GOVERNANCE.md`.

To keep that regression role stable, the small-OBD CI bootstrap constrains third-party OBD dependencies to the already accepted full-OBD environment snapshot at `benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/environment.txt`, verifies every exact persisted distribution pin, and rejects unexpected external distributions before the small dataset is fetched. The regression job uses the explicit Ubuntu 24.04 runner family, while the general Python compatibility and package jobs deliberately remain on `ubuntu-latest`. Because ordinary CI runs on every push to `main`, the same OBD integration job also serves as the trusted default-branch pip-cache producer; a separate cache-seeding workflow would duplicate the frozen install and race to reserve the same cache key.

Those controls narrow environmental variation but do not promise bit-for-bit floating-point identity across GitHub-hosted machines. Hosted instances can differ in physical CPU and numerical-library execution details even when the OS version, hosted image build, Python version, package versions, and random seeds match. Small differences in fitted Q values can therefore change JSONL-derived tuning/test fingerprints without changing the experiment plan, data identity, support diagnostics, or selected estimator. The small-OBD artifact records CPU, NumPy build configuration, threadpool/BLAS metadata, thread-related environment variables, Python, and OS/image provenance before data access so such differences can be diagnosed.

Development comparisons should recompute their baseline inside the same run. Tiny floating-point differences across hosted hardware are not evidence that a method improved and must not be converted into a rerun-until-winning process. Raw tuning/test fingerprints that include floating predictions are evidence identities for a particular realized run, not cross-host bitwise-stability gates. Regression interpretation should prioritize frozen protocol/data/environment identities and material numerical discrepancies; benign last-bit variation must not be used as a promotion signal.

## When a manual full-data run is admissible

A manual run is appropriate for one of two purposes.

### 1. Replication of an accepted experiment

A replication may rerun the exact frozen source, plan, candidate configuration, split, seeds, selection contract, dependency environment, and operating-system family to test reproducibility.

The current full-data workflows use their persisted accepted environment snapshots as replication constraint sources and verify every exact installed distribution pin before real benchmark data may be accessed:

- Criteo: `benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/environment.txt`;
- OBD: `benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/environment.txt`.

Both accepted full-data runs were produced on the GitHub-hosted Ubuntu 24.04 family. The replication workflows therefore use the explicit `ubuntu-24.04` runner label instead of the moving `ubuntu-latest` alias. GitHub does not expose a hosted-runner label for an exact image build, so each future run records the resolved image metadata, architecture, kernel, libc, and `/etc/os-release` into `runner-environment.txt` and uploads it with the evidence bundle. An image patch revision may vary while remaining within the accepted OS family; any material numerical discrepancy must still be investigated rather than normalized away.

Changing either frozen dependency baseline or the operating-system family is not an in-place replication; it is a new experiment environment and must receive a new preregistered identity rather than overwriting accepted evidence.

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
- selection objective;
- frozen dependency environment;
- operating-system family.

The new experiment must receive a new plan/fingerprint and a new evidence directory. The previous final holdout result must not be used as a tuning signal for the new candidate set. Its implementation must first pass ordinary review and enter `main`; only then is a manual full-data dispatch admissible.

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

The accepted evidence directories are continuously checked by `tests/test_persisted_evidence.py`. The workflow trigger contract is continuously checked by `tests/test_research_workflow_policy.py` and `tests/test_full_research_dispatch_policy.py`.
