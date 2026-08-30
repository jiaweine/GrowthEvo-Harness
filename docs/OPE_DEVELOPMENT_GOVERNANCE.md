# OPE Development Cohort Governance

GrowthEvo separates **development evidence** from accepted locked benchmark evidence. A development validation cohort can be useful for comparing a predeclared set of ideas, but repeated adaptive screening against the same revealed validation reference eventually makes that cohort unsuitable for further promotion decisions.

## Exhausted small Open Bandit cohort

The cohort identified by `benchmarks/ope/obd-small-all-random-to-bts.v1.json` is now **exhausted for promotion research**.

Its machine-readable status is recorded in:

`benchmarks/ope/development/obd-small-all-random-to-bts.v1.json`

The base plan fingerprint is:

`d8ac714101799258f5202723ca3490e3b6b3c600`

The validation reference has already been revealed and the same cohort has been used for multiple sequential method screens, including Meta-OPE alignment, beta-DR, empirical-likelihood EMP, SNDR, RandomForest Q, and MRDR-trained Q. Each experiment was rejected without using the final holdout to rescue the method, but continuing to propose methods after observing these validation outcomes would itself create adaptive validation-shopping risk.

## What exhausted means

The cohort may still be used for:

- deterministic regression tests;
- exporter/integration checks;
- reproduction of an already recorded development attempt;
- checking that an implementation change preserves an existing result within an explicitly stated numerical tolerance.

It must **not** be used to justify promotion of:

- a new OPE estimator;
- a new Q-model backend or nuisance objective;
- new estimator/Q hyperparameters;
- a new candidate grid assembled after observing previous development results.

The normal CI small-OBD job is therefore still valid: it is an integration/regression gate, not a source of new promotion claims.

## Requirement for future OPE research

A future OPE method that needs empirical promotion evidence must use a **new preregistered development identity before its validation evidence is opened**. The new identity must freeze at least the data source/release, split, target policy, Q protocol, candidate set, selection objective, and evidence gates that are material to the comparison.

Synthetic tests and faithful literature reproductions can be developed without creating a new real-world cohort. They become promotion candidates only after a fresh preregistered empirical protocol exists.

Accepted full OBD evidence remains separate and locked. The accepted full-data holdout must not be reused to compensate for an exhausted development cohort.

## Same-run comparison and floating point

Hosted research jobs may show tiny cross-run floating-point differences even when the declared numerical package versions match. Development decisions must therefore compare a candidate against a baseline **recomputed inside the same run**, rather than asserting an old absolute-error constant from another runner.

Such numerical drift is not permission to retune thresholds or rerun until a candidate wins. Material reproducibility discrepancies should be investigated under `docs/RESEARCH_RERUN_POLICY.md`.
