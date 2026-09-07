# Nonstationary right-heavy-tail lower confidence sequence

This module addresses one specific failure mode from the GrowthEvo sequential
stress lab: a positive metric whose conditional mean can change over time while
individual observations are nonnegative and may have a very heavy right tail.

It is intentionally separate from the stationary finite-variance Catoni effect
monitor. It does not replace the bounded Hoeffding canary e-process, group-
sequential primary test, experiment-integrity gate, maturity contract, or cluster
outcome contract.

## Estimand

Let `X_t >= 0` be adapted observations and

`m_t = E[X_t | F_(t-1)]`.

GrowthEvo assumes a preregistered finite constant `M` such that

`0 <= m_t <= M`

for every monitored time. Importantly, **the observations themselves need not be
bounded by `M`**.

The target at time `t` is the running average conditional mean

`mu_bar_t = (1/t) sum_{i=1}^t m_i`.

This is a genuinely nonstationary estimand: `m_t` may move over time. It is not a
fixed stationary population mean.

## Normalization and predictable center

Set

`Z_t = X_t / M`.

Then `Z_t >= 0` and its conditional mean lies in `[0,1]`, although `Z_t` itself can
be arbitrarily larger than `1`.

Before seeing `Z_t`, GrowthEvo chooses the predictable center

`p_t = min(1, (sum_{i<t} Z_i + c) / t)`

where `c` is the frozen `predictor_pseudocount` (default `0.5`). The center affects
power but not the target estimand.

## Betting process

For a frozen `lambda in (0,1)`, define

`e_t = Z_t - p_t`

and

`V_t(lambda) = sum [lambda e_t - log(1 + lambda e_t)]`.

For the true running average conditional mean, the wealth can be written

`W_t = exp(lambda(sum Z_i - sum E[Z_i|F_(i-1)]) - V_t(lambda))`.

Equivalently, the one-step conditional expected multiplier is

`(1+a_t) exp(-a_t)`

where

`a_t = lambda(E[Z_t|F_(t-1)] - p_t)`.

Because both the conditional mean and `p_t` lie in `[0,1]` and `lambda<1`, the
multiplier stays positive. The elementary inequality

`(1+a) exp(-a) <= 1` for `a > -1`

makes the wealth a nonnegative supermartingale. Ville's inequality therefore gives
anytime-valid lower confidence evidence.

GrowthEvo freezes a finite equal-weight mixture of lambda values before observing
data. A convex mixture of the component supermartingales remains a
supermartingale. Inverting that mixture over `[0,M]` produces the lower confidence
sequence for `mu_bar_t`.

## Fixed finite mixture in v1

The default lambda grid is

`(0.05, 0.1, 0.2, 0.4, 0.7)`.

This v1 deliberately uses a small fixed mixture because it is dependency-free,
auditable, and exact for the implemented betting construction.

Microsoft's public `csrobust` reference implementation uses a more adaptive
countable-discrete mixture and additional approximation machinery for better
power/computational scaling. GrowthEvo does not silently claim those stronger
implementation properties. A future adaptive/countable mixture must have a new
protocol identity and its own tests.

## Observation cap versus mean cap

`mean_upper` is a bound on the **conditional mean**, not an outcome clipping
threshold.

For example, with `mean_upper=1`, an observation of `1000` is legal. The method
absorbs that right-tail event through the logarithmic betting correction instead
of clipping it to `1`.

This distinction is essential. Clipping would change the estimand unless a separate
bias correction or assumption were added.

## Absolute positive-metric floor monitor

`NonstationaryPositiveMetricMonitor` wraps the lower CS for a positive KPI and a
preregistered absolute floor.

It can emit:

- `HOLD`; or
- `ABOVE_FLOOR` when the anytime-valid lower bound exceeds the floor.

It **cannot** emit a statistically justified `BELOW_FLOOR` from a lower confidence
sequence. Absence of positive evidence is not evidence of harm.

This is appropriate for assertions such as:

- running average successful-task value remains above a required minimum;
- running average positive utility exceeds a launch floor;
- a nonnegative reliability/value measure clears an absolute threshold.

## Nonstationary off-policy value

For a target policy evaluated against a logging policy, let `w_t >= 0` be the
correct predictable likelihood ratio and let reward satisfy

`0 <= R_t <= R_max`.

The importance-weighted observation

`X_t = w_t R_t`

can be unbounded even though reward is bounded. Under valid importance weights,
its conditional mean is the target policy's conditional value and is at most
`R_max`. Therefore the same changing-mean lower-CS construction can lower-bound the
running average counterfactual policy value.

`ChangingMeanOffPolicyValueMonitor` implements this typed use case. Correctness
requires:

1. the weight is the valid likelihood ratio for the target policy relative to the
   logging policy;
2. logging support exists wherever the target policy acts;
3. the reward bound is correct;
4. each observation contributes once under the intended analysis-unit contract.

The monitor does not estimate or repair invalid propensities.

## What this does not prove

### It is not a signed treatment-effect confidence sequence

A treatment-control difference is signed. This lower-CS construction requires a
nonnegative scalar. Running separate lower bounds for challenger and control does
not automatically produce a valid confidence sequence for their difference.

Use the stationary randomized-effect protocol when its assumptions hold, or a
future explicitly derived nonstationary effect protocol. Do not subtract two lower
bounds and call the result an ATE bound.

### It does not repair SRM

A mathematically valid wealth process cannot rescue a corrupted assignment or
analysis population. Experiment integrity remains a separate authority.

### It does not repair censoring

Differential endpoint maturity or missing outcomes require the maturity contract
and, if incomplete outcomes are to be analyzed, a separately identified censoring
estimator.

### It does not repair repeated-event pseudoreplication

When randomization occurs at user/account/workspace level, repeated events must be
collapsed according to the cluster-outcome contract before they can count as
independent analysis units.

### It does not infer a mean cap from current treatment outcomes

`mean_upper` is part of the preregistered identifying/statistical contract. Choosing
it after viewing live effects invalidates the intended guarantee.

## Protocol identity

`ChangingMeanLowerCSSpec` fingerprints:

- `mean_upper`;
- alpha;
- lambda grid;
- predictable-center pseudocount;
- numerical root contract;
- target estimand and support assumptions.

`NonstationaryFloorSpec` additionally binds the KPI and floor.

`ChangingMeanOffPolicySpec` additionally binds the bounded reward scale, value
floor, and counterfactual-value estimand.

A semantic change therefore cannot silently reuse old evidence.

## Privacy and atomicity

The wrapper monitors keep only experiment-scoped BLAKE2 analysis-unit tokens for
deduplication. Raw identifiers are not retained in the evidence state.

Numerical validation is completed before the dedupe token is committed. An invalid
or overflowing observation therefore cannot consume an analysis unit and cannot
partially mutate the evidence stream.

## References

- Paul Mineiro, *A lower confidence sequence for the changing mean of non-negative
  right heavy-tailed observations with bounded mean* (2022).
- Microsoft `csrobust`, public robust confidence-sequence reference implementation:
  https://github.com/microsoft/csrobust

The references motivate the statistical direction. The GrowthEvo code, tests, and
versioned fingerprints define the exact implemented protocol.
