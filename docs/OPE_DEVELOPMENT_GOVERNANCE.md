# OPE Development Cohort Governance

GrowthEvo separates **development cohorts** from accepted locked benchmark evidence. This keeps rapid estimator engineering compatible with an independent promotion path.

## Small Open Bandit development cohort

The cohort identified by `benchmarks/ope/obd-small-all-random-to-bts.v1.json` is retained as a **regression and integration cohort**.

Its machine-readable development record is stored at:

`benchmarks/ope/development/obd-small-all-random-to-bts.v1.json`

Base plan fingerprint:

`d8ac714101799258f5202723ca3490e3b6b3c600`

The cohort has already supported multiple sequential method-development comparisons, including Meta-OPE alignment, beta-DR, empirical-likelihood EMP, SNDR, RandomForest Q, and MRDR-trained Q. That history makes it especially valuable as a stable regression surface for implementation behavior.

## Intended use

The existing cohort is well suited to:

- deterministic regression tests;
- exporter and integration checks;
- reproduction of recorded development attempts;
- same-run baseline comparisons;
- numerical-tolerance checks after implementation changes.

New promotion research uses a **fresh preregistered development identity** before validation evidence is opened. This keeps new estimator or Q-model selection independent of earlier method-development observations while preserving the existing cohort as a durable engineering asset.

## New development identities

A new empirical development identity freezes the choices material to the comparison, including:

- data source and release;
- split definition;
- target policy;
- Q-model protocol;
- candidate estimator set;
- selection objective;
- support and evidence gates.

Synthetic tests and faithful literature reproductions can be developed independently of a new real-world cohort. When empirical promotion evidence is needed, the new preregistered identity provides the validation surface for that decision.

Accepted full OBD evidence remains a separate locked artifact with its own plan, validation selection, final holdout, and provenance chain.

## Same-run comparison and numerical stability

Hosted research jobs can exhibit small cross-run floating-point differences even under matched numerical-package versions. Development comparisons therefore favor a baseline recomputed in the same run when a candidate is sensitive to numerical precision.

Material reproducibility differences are investigated under `docs/RESEARCH_RERUN_POLICY.md`, while accepted evidence remains tied to its original persisted environment and fingerprints.

## Why this structure matters

The two-tier design gives GrowthEvo both:

1. a stable small-data regression cohort for fast engineering iteration; and
2. fresh preregistered development identities for statistically clean promotion comparisons.

This keeps OPE research iterative without turning accepted benchmark evidence into an evolving tuning surface.
