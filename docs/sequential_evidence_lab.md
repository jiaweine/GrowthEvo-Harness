# Sequential Evidence Lab

GrowthEvo treats statistical protocols as code that must themselves be evaluated before they are trusted for production promotion decisions.

A unit test proves that an implementation runs and satisfies local invariants. It does **not** prove that a sequential design controls false positives, has useful power, or detects harmful challengers quickly enough under a declared data-generating process (DGP).

The Sequential Evidence Lab adds a separate operating-characteristics gate:

```text
protocol implementation
        -> frozen simulation plan
        -> deterministic Monte Carlo runs
        -> uncertainty-aware operating characteristics
        -> pre-registered acceptance gates
        -> acceptance artifact
        -> optional protocol certificate
```

The certificate is governance evidence for a declared scenario family. It is not a mathematical theorem and it is not a substitute for validating additional real-world assumptions.

## Current scope

The first lab version evaluates two existing GrowthEvo paths:

1. `group_sequential_primary` — the planned-look primary-success monitor from `HighPowerCanaryPlan`;
2. `anytime_primary_eprocess` — the bounded Hoeffding-mixture primary-success process from the base canary.

Both are evaluated on a randomized bounded Bernoulli DGP. The lab also simulates a harmful challenger and measures the anytime e-process rollback detector used by the online safety layer.

Clustered, survival, censored, network-interference and covariate-adaptive DGPs are intentionally **not** silently approximated by this scenario. They should be added as new typed scenario identities with their own acceptance artifacts.

## Frozen scenario

`BernoulliSequentialScenario` pre-registers:

- control outcome probability;
- positive challenger effect on GrowthEvo's oriented metric scale;
- negative harmful effect;
- maximum observation horizon;
- optional covariate/outcome association used when a frozen CUPED transform is present.

The oriented scale follows the online promotion contract:

```text
positive effect = challenger better
negative effect = challenger worse
```

For lower-is-better metrics, the simulator converts the oriented effect back to the raw metric direction before generating outcomes.

The Bernoulli DGP requires the declared primary metric bounds to contain `[0, 1]`. A different outcome family should use a different scenario type rather than exploiting those bounds accidentally.

## Reproducibility and seed hygiene

`SequentialEvidenceLabPlan` contains a base seed, but each operating-characteristic stream derives an independent deterministic seed from:

- base seed;
- complete lab-plan fingerprint;
- protocol name;
- scenario role (`null`, `benefit`, or `harm`).

This prevents the null, power and harm checks from consuming the same pseudo-random stream while making the artifact exactly reproducible for a frozen implementation and plan.

Changing the DGP, random seed, acceptance criteria, group-sequential plan, CUPED contract, e-process bets or base canary plan changes a fingerprint.

## Monte Carlo uncertainty is part of the gate

A simulated false-positive estimate is itself noisy. GrowthEvo therefore does not accept a protocol because the point estimate happens to be below a threshold.

For each simulated binomial operating characteristic it records a Wilson confidence interval:

- Type-I error is compared using the **upper** confidence bound;
- power is compared using the **lower** confidence bound;
- harm-detection probability is compared using the **lower** confidence bound.

This creates a deliberately asymmetric fail-closed gate.

For example, a point estimate of `0.048` does not by itself establish a 5% false-positive guarantee. If its Monte Carlo upper confidence bound exceeds the pre-registered ceiling, the protocol fails the lab gate.

## Minimum simulation size

`MonteCarloAcceptanceGate.minimum_replications` cannot be configured below 1000.

A smaller run remains useful for:

- local debugging;
- CI smoke testing;
- checking deterministic reproducibility;
- comparing gross protocol behavior.

But it cannot produce `acceptance_passed=True` solely by lowering the minimum-replication policy below 1000.

Production statistical validation should normally use substantially more than the hard minimum when the accepted Type-I ceiling is close to the nominal alpha, when effects are small, or when rare guardrail failures matter.

## Operating characteristics

Each protocol result records:

- simulated Type-I error with Monte Carlo interval;
- simulated power with Monte Carlo interval;
- harmful-challenger detection probability with interval;
- mean benefit stopping observations;
- mean benefit stopping fraction of the protocol horizon;
- mean rollback-delay observations;
- mean rollback-delay fraction of the harm-simulation horizon.

The group-sequential success path uses the expected final-stage observation count from `GroupSequentialSpec` as its success horizon. The anytime path uses the simulation scenario horizon.

Safety remains the existing anytime e-process in both cases, so the lab evaluates that rollback behavior as part of the combined production posture.

## Acceptance

`MonteCarloAcceptanceGate` pre-registers:

- maximum Type-I upper confidence bound;
- minimum power lower confidence bound;
- minimum harm-detection lower confidence bound;
- maximum mean rollback-delay fraction;
- Monte Carlo confidence level;
- minimum replication count.

Every declared condition is conjunctive. A high-power design does not pass if it has unacceptable false positives or weak harm detection.

`SequentialEvidenceLabArtifact.acceptance_reasons` records every failed gate instead of returning only the first failure.

## Protocol certificate

`SequentialProtocolCertificate.from_artifact(...)` is available only for an accepted artifact.

The certificate binds:

- source code commit;
- high-power canary-plan fingerprint;
- lab-plan fingerprint;
- complete lab-artifact fingerprint;
- scenario fingerprint.

The certificate is intentionally not wired into the current online controller. The existing production paths remain unchanged. Future experimental statistical backends can choose to require a certificate before they are exposed as promotion-authority protocols.

This sequencing avoids a circular dependency where a new method gets production authority merely because it can generate its own certificate.

## What the lab does not prove

Passing a simulation gate means:

> under the declared DGP, horizon, randomization and protocol implementation, the measured operating characteristics satisfy the pre-registered Monte Carlo acceptance criteria with the declared simulation uncertainty.

It does **not** establish correctness under arbitrary:

- heavy-tailed outcomes;
- unmodeled clustering;
- repeated-user pseudo-replication;
- interference or network effects;
- missing-not-at-random outcomes;
- delayed censoring;
- broken randomization;
- treatment-dependent covariates;
- post-hoc CUPED fitting;
- adaptive protocol changes after interim results.

Those require either stronger theory, additional scenario families, or both.

## Relationship to the high-power canary

The intended development lifecycle is now:

```text
new sequential method
    -> unit/property tests
    -> typed protocol fingerprint
    -> Sequential Evidence Lab
    -> operating-characteristics artifact
    -> optional certificate
    -> shadow / non-authoritative integration
    -> only then consider production authority
```

This extends GrowthEvo's evidence hierarchy inward: not only must an LLM candidate earn authority through causal evidence, the statistical machinery used to judge that candidate must earn authority through its own reproducible validation evidence.

## Future scenario families

The next useful additions are deliberately separate protocol/DGP identities:

- exact numerical Lan-DeMets boundaries with a validated multivariate-normal backend;
- regression-adjusted / doubly-robust anytime-valid ATE confidence sequences;
- cluster-randomized and repeated-user designs;
- delayed and right-censored outcomes;
- survival endpoints;
- covariate-adaptive randomization with predictable logged propensities;
- sample-ratio-mismatch and assignment-corruption stress scenarios;
- nonstationary and heterogeneous treatment-effect stress tests.

Each new family should ship with operating-characteristic tests before it is allowed to influence champion promotion.
