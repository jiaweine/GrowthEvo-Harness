# Robust heavy-tail sequential inference

This document defines GrowthEvo's optional finite-variance heavy-tail evidence plane.
It does **not** replace the existing bounded Hoeffding e-process, group-sequential
primary gate, experiment-integrity gate, outcome-maturity contract, or
cluster-outcome contract.

The purpose is narrower: when a randomized metric is naturally unbounded or very
right-skewed, avoid forcing an arbitrary hard range merely so a bounded-mean
sequential test can run.

## Statistical target

For one unique randomized analysis unit, let

`A_t in {0,1}` be challenger assignment,

`p_t` be the known assignment probability, and

`Y_t` be the observed endpoint.

GrowthEvo constructs the Horvitz-Thompson contribution

`Z_t = A_t Y_t / p_t - (1-A_t) Y_t / (1-p_t)`.

For lower-is-better metrics the sign is reversed. Positive therefore always means
the challenger is better.

Version 1 targets the typed estimand

`stationary_randomized_ht_mean_effect`.

The required model contract is deliberately explicit:

1. randomized, correctly logged assignment with predictable propensities;
2. one contribution per independent randomized analysis unit;
3. a constant conditional mean for `Z_t` over the monitored segment;
4. a preregistered finite upper bound `v` on the conditional central variance of
   `Z_t`;
5. finite observed outcomes;
6. no unmodeled interference across analysis units.

The variance bound is on the **HT contribution**, not directly on raw outcome
variance. A raw revenue variance estimate is not automatically a valid value for
this field.

## Catoni influence

GrowthEvo uses the odd influence function

`phi(x) = log(1 + x + x^2/2)` for `x >= 0`,

and

`phi(x) = -log(1 - x + x^2/2)` for `x < 0`.

It satisfies the exponential envelope used by Catoni-style robust mean confidence
sequences. For a candidate mean `mu`, positive predictable `lambda`, and
conditional variance bounded by `v`, the point-parameter process

`exp(sum phi(lambda (Z_t - mu)) - lambda^2 v t / 2)`

is a nonnegative supermartingale when the conditional mean equals `mu`. The
sign-reversed counterpart provides the other side.

GrowthEvo fixes a finite mixture of positive lambda values before observing data.
A convex mixture of those supermartingales remains a supermartingale. Each side
receives `alpha/2`, and inversion produces a two-sided anytime-valid confidence
sequence.

The default dimensionless lambda scales are:

`(0.125, 0.25, 0.5, 1.0, 2.0)`.

Actual lambda values are those scales divided by the preregistered standard-
deviation bound `sqrt(v)`.

Changing the variance bound, alpha, lambda grid, or root-inversion contract changes
the versioned `CatoniMixtureSpec` fingerprint.

## Why this is not winsorization

A fixed winsorization threshold changes the estimand to a clipped mean unless a
separate bias correction/assumption is supplied. GrowthEvo does not silently clip
an unbounded metric and continue calling the result the original mean effect.

This robust-CS path keeps the original mean estimand under a finite-variance
assumption instead.

## Randomized effect monitor

`RobustRandomizedEffectMonitor`:

- requires a unique analysis-unit identifier;
- hashes that identifier with the experiment ID for dedupe state;
- verifies the propensity support floor;
- forms one oriented HT contribution;
- rejects numeric overflow atomically;
- updates the Catoni mixture confidence sequence;
- emits evidence only.

It does **not** ramp traffic, mutate the champion, or override any other authority.

`SUPPORTS_SUPERIORITY` requires the lower confidence-sequence bound to exceed the
preregistered superiority margin.

`SUPPORTS_HARM` requires the upper bound to fall below the preregistered harm
margin.

Otherwise the decision is `HOLD`.

These are single-metric statements. Multiple metrics still require a separate
family-wise alpha allocation contract.

## Composition with other GrowthEvo authorities

This module addresses only heavy tails. A valid live path still needs the relevant
orthogonal contracts:

- SRM / assignment integrity: `ExperimentIntegrityGate`;
- delayed or missing outcomes: `OutcomeMaturityLedger` or a future explicit
  censoring estimator;
- repeated events within a randomized user/account: `ClusterOutcomeAccumulator`;
- legal, budget, fatigue, churn, consent and policy constraints: existing runtime
  authorities;
- nonstationary effects: **not solved by this v1 module**.

A robust estimator cannot repair a broken experiment population.

## What v1 intentionally does not implement

### Nonstationary running-mean confidence sequences

Recent robust-CS work, including Microsoft's `csrobust`, demonstrates methods for
running conditional means in nonstationary environments and for some right-heavy-
tailed processes. Those methods have a larger proof and implementation surface.
GrowthEvo v1 therefore does not silently claim their guarantees.

### Infinite-variance p-moment inference

Catoni-style confidence-sequence research also covers settings with only a finite
`p`-th central moment for `1 < p < 2`. GrowthEvo v1 requires a finite variance
bound. A p-moment mode should be a separately fingerprinted protocol.

### Adaptive nuisance fitting

This module does not estimate the variance bound from current treatment outcomes,
does not tune lambda after inspecting effect results, and does not fit a reward
model on the live evidence stream.

## Operational rule

If a trustworthy variance bound cannot be preregistered, this module must not be
used for promotion authority. The correct state is `HOLD` or a separately designed
protocol, not an optimistic guessed variance cap.

## References

- Hongjian Wang and Aaditya Ramdas, *Catoni-style confidence sequences for
  heavy-tailed mean estimation*, Stochastic Processes and their Applications 163
  (2023), 168-202. DOI: 10.1016/j.spa.2023.05.007.
- Microsoft `csrobust`, robust confidence sequences:
  https://github.com/microsoft/csrobust

These references motivate the statistical direction. GrowthEvo's code and protocol
identity define the exact implemented contract.
