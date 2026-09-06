# Cluster-safe outcome aggregation contract

GrowthEvo's online canary already requires one matured outcome per randomized analysis unit. That contract is only as strong as the upstream pipeline. If a randomized user produces ten events and the pipeline sends ten different event IDs as if they were ten randomized units, ordinary deduplication cannot recover the causal design.

This module moves the protection upstream:

> one randomized cluster may contain many repeated events, but it emits exactly one frozen cluster-level outcome into the canary.

The v1 contract is intentionally a **cluster-level aggregation** contract. It is not presented as a general cluster-robust regression or GEE implementation.

## Why the randomization unit matters

Outcomes from the same randomized cluster are correlated. Treating repeated observations from one randomized user/account/workspace as independent units creates a unit-of-analysis error and typically understates uncertainty.

Cluster-randomized trial methodology makes the same point: clustering must be accounted for in the analysis, either through a cluster-level analysis or an individual-level method that explicitly models/robustifies within-cluster dependence.

GrowthEvo v1 chooses the narrowest auditable option for the common product case in which the **cluster itself is randomized**:

1. assign the user/account/workspace once;
2. collect repeated events only inside a preregistered window;
3. aggregate them deterministically;
4. finalize one bounded outcome;
5. submit that one outcome as the canary analysis unit.

If dependence exists across these randomized clusters as well, this contract is insufficient and a cluster-robust higher-level estimator is still required.

## ClusterOutcomeSpec

The spec freezes:

- metric name;
- aggregation rule;
- event window;
- per-event bounds;
- finalized outcome bounds;
- maximum number of accepted events;
- the empty-cluster outcome;
- estimand identity.

Every change produces a new `growthevo.cluster-outcome-spec.v1` fingerprint.

## Supported aggregation modes

### `mean`

The cluster outcome is the arithmetic mean of accepted event values. The declared outcome bounds must contain the full per-event range.

### `sum`

The cluster outcome is the sum of accepted values. `max_events` is part of the statistical contract because it determines the largest representable bounded sum. The declared outcome bounds must contain every sum possible under the frozen event bounds and event-count limit.

GrowthEvo rejects an event that would exceed `max_events`; it does not silently truncate the tail of the event stream.

### `binary_any`

The cluster outcome is `1` if any accepted event is positive and `0` otherwise. Per-event values must lie in `[0,1]`, the finalized bounds must contain `[0,1]`, and the empty-cluster value is fixed to zero.

## Empty clusters are an estimand choice

A randomized cluster may produce no events during the window. That is still an experimental unit, not a row to be dropped.

`empty_value` is therefore preregistered. For example:

- zero revenue over the window naturally maps to `0`;
- no conversion event under `binary_any` maps to `0`;
- a mean of an event property may need a product-specific empty-cluster definition before the metric can be used.

Dropping no-event clusters after randomization can create post-treatment selection and is not allowed by this accumulator.

## Frozen window and event identity

Each cluster receives a `ClusterAssignmentTicket` at exposure with:

- randomized arm;
- exposure timestamp;
- frozen window end;
- spec fingerprint;
- ticket fingerprint.

Events are accepted only when:

- the cluster was registered;
- the event timestamp lies inside the frozen exposure window;
- the event value is finite and inside preregistered bounds;
- the event ID has not already been seen for that cluster;
- the cluster has not exceeded `max_events`;
- the cluster has not already been finalized.

Event IDs are converted to experiment-scoped hashes before being stored.

## One final result, one canary observation

`finalize()` is unavailable before the cluster window matures. After finalization, later events are rejected.

The final `ClusterOutcomeResult` contains one bounded metric value and the accepted event count. It can be converted to:

- a normal `CanaryObservation` using the original `CanaryRoute`; or
- a `HighPowerCanaryObservation` using the original `HighPowerExposureTicket`.

Both conversions verify cluster identity and randomized arm. A mismatched route/ticket fails closed.

This means fifty events from one randomized account still become exactly **one** observation in the causal monitor.

## Estimand: typical cluster

The only v1 estimand is:

`typical_cluster`

Each finalized randomized cluster contributes one outcome with equal cluster weight.

This is deliberate. A cluster-level mean followed by equal cluster weighting generally targets a different quantity from a typical-individual estimand when cluster sizes vary. GrowthEvo does not silently make large clusters count more because they emitted more events.

If the product question is instead about the typical individual, user-weighted impact, or another size-weighted estimand, that must be represented by a different typed protocol with its own weighting and inference contract.

## Privacy and provenance

Internal accumulator state stores:

- experiment-scoped cluster hashes;
- experiment/cluster-scoped event hashes;
- event times and values needed for the declared aggregate;
- ticket and result fingerprints.

Raw cluster IDs and raw event IDs are not retained internally after the API call. The returned ticket/result contains the caller's cluster ID only so it can be joined back to the already-existing routing API.

`cohort_fingerprint()` binds the full hashed cluster/event manifest and finalized-result identities without exposing those raw IDs.

## Relationship to other GrowthEvo contracts

The contracts solve different layers:

- `CanaryRouter` / `HighPowerExposureTicket`: who was randomized, to which arm and stage;
- `ClusterOutcomeAccumulator`: how repeated events become one randomized-unit outcome;
- `OutcomeMaturityLedger`: when a delayed endpoint is mature and whether the frozen cohort is complete;
- `ExperimentIntegrityGate`: whether enrollment/matured arm ratios remain trustworthy;
- online sequential inference: whether the finalized randomized-unit outcomes justify ramp, rollback, or promotion.

A production integration may bind all of them to the same cluster ID, but none substitutes for another.

## What this does not solve

Cluster-level aggregation is sufficient only when it matches the declared randomized unit and estimand assumptions. It does not by itself solve:

- interference between randomized clusters;
- households nested inside regions when treatment is randomized at region level;
- time-varying cluster membership;
- unequal-cluster weighting for a typical-individual estimand;
- a small number of clusters requiring corrected inference;
- cluster crossover or stepped-wedge dependence;
- missing cluster outcomes.

Those require a different analysis protocol, such as cluster-robust variance, GEE/mixed models, cluster-level randomization inference, or another validated estimator.

## Research references

Cluster-randomized methodology consistently warns that within-cluster correlation must be accounted for and that ignoring it creates a unit-of-analysis error. Cluster-level summaries are one valid approach when they match the intended estimand; individual-level approaches require explicit methods such as mixed models, GEE, or cluster-robust inference.

The GrowthEvo design therefore treats aggregation semantics and estimand identity as part of the protocol fingerprint rather than as a downstream dataframe convenience.
