# High-Power Sequential Causal Promotion

This protocol is an **optional** successor to the conservative online-canary success gate. It does not replace GrowthEvo's locked offline evaluation, randomized routing, anytime-valid deterioration monitoring, legal constraints, or rollback path.

The design goal is narrower:

> when a credible final-stage sample size can be pre-registered, use fewer planned success looks and frozen pre-exposure variance reduction to obtain more power without weakening continuous safety monitoring.

The original `OnlinePromotionController` remains unchanged. The advanced path is enabled only by constructing `HighPowerOnlinePromotionController` with a `HighPowerCanaryPlan`.

## Split the safety question from the success question

GrowthEvo now supports two different sequential tools for two different jobs.

### Safety / deterioration

The existing bounded Hoeffding mixture e-process remains active continuously for:

- relative harm;
- non-inferiority;
- absolute guardrails;
- deterministic cumulative-cost rollback.

These checks may run after every matured randomized analysis unit because early detection of harm is worth the power cost.

### Primary success

The high-power path does **not** continuously test primary superiority. Instead, it performs a small number of pre-registered group-sequential looks during the final rollout stage.

For example:

```text
final-stage expected matured units = 40,000
planned looks = 25%, 50%, 75%, 100%
```

The candidate cannot become champion between those looks. Safety can still roll it back at any time.

This separation avoids paying an infinite-look penalty for the primary success claim when the system already knows a reasonable maximum sample size.

## Group-sequential reference gate

`GroupSequentialSpec` freezes:

- expected final-stage matured analysis units;
- information/look fractions;
- family alpha;
- alpha-spending rule;
- minimum observations required in each randomized arm.

The dependency-free reference implementation computes a Welch-style one-sided z statistic at each planned look. It offers two conservative spending schedules:

- `equal`;
- `obrien_fleming`-shaped cumulative spending.

The implementation deliberately uses each incremental alpha allocation as a per-look rejection threshold. The allocations sum to no more than the configured family alpha, so this reference is conservative without requiring SciPy or a multivariate-normal integration dependency.

It is **not** presented as an exact Lan-DeMets correlated-boundary implementation. A production platform with a validated numerical statistics stack can add an exact boundary calculator behind a new fingerprinted protocol identity.

## Why a separate protocol identity matters

Changing from always-valid inference to group-sequential inference changes the stopping rule and statistical assumptions. It is therefore not a tuning flag hidden under the old plan.

`HighPowerCanaryPlan.fingerprint` binds:

- the complete base canary plan;
- the group-sequential design;
- the frozen CUPED contract, if used;
- the declared randomization/analysis-unit name.

A change to expected sample size, look schedule, alpha, CUPED coefficient, CUPED centering, source reference data, or analysis unit creates a different plan fingerprint.

## Frozen CUPED variance reduction

`FrozenCUPEDSpec` supports pre-exposure variance reduction for the primary metric:

```text
Y_adjusted = Y - theta * (X_pre - center)
```

where `X_pre` is a bounded pre-treatment covariate.

The coefficient `theta`, center, covariate bounds, and source fingerprint must be estimated/frozen from pre-exposure or otherwise independent reference data **before online treatment outcomes are inspected**.

The online controller does not refit CUPED after interim looks. This is intentional. Changing covariate adjustment after seeing interim data can invalidate group-sequential Type-I-error guarantees and can create biased or anti-conservative inference.

If the frozen covariate is missing, non-finite, or outside its pre-registered bounds, the advanced primary analysis fails closed for that observation instead of silently imputing or clipping it.

## Delayed outcomes: freeze the exposure stage

The original immediate-outcome canary validates an outcome against the currently active traffic stage. That is fine when outcomes mature before the stage changes, but it is not enough for delayed metrics.

The advanced controller introduces `HighPowerExposureTicket`.

At exposure time, the ticket freezes:

- analysis-unit ID (ephemeral caller-side value);
- routing-stage index;
- in-canary decision;
- champion/challenger arm;
- traffic fraction;
- randomized arm probability.

A matured outcome carries that original `routing_stage_index`. The controller recomputes the deterministic route for the **exposure stage**, not the stage that happens to be active when the delayed outcome arrives.

A valid old-stage delayed outcome may still update cumulative safety evidence, but it does **not** count toward the current stage's minimum matured-outcome quota and does not enter the final-stage primary group-sequential test unless it was originally exposed in the final stage.

This prevents pipeline outcomes from artificially filling a later-stage quota.

## Repeated-user / cluster contract

The analysis unit is also the randomization cluster.

Examples:

- `user`;
- `account`;
- `household`;
- `workspace`.

Each randomized analysis unit can contribute only **one matured bounded outcome vector** to a plan. If a user generates many events, aggregate those events upstream into the pre-registered user-level metric window before submission.

This design avoids pretending that many events from the same randomized user are independent samples. More sophisticated repeated-measures/GEE or cluster-randomized sequential estimators can be added later, but they must use a new evidence protocol and operating-characteristic validation.

## Final-stage data are fresh for success

The high-power primary monitor ingests only units whose exposure ticket was created in the final rollout stage.

Earlier-stage units still contribute to safety/non-inferiority evidence, but they are not reused in the planned primary-success analysis. This preserves the existing GrowthEvo separation between ramp evidence and final success evidence while allowing multiple *pre-registered* looks inside the final stage.

## Terminal decisions

During the final stage:

- if continuous safety evidence detects harm, rollback immediately;
- if a planned primary look crosses its allocated success threshold and all safety gates pass, promote the challenger;
- if the final planned look is exhausted without superiority, stop the challenger and keep the original champion.

The last case is represented as a fail-closed rollback because the candidate has consumed its pre-registered success budget without earning promotion authority.

## Sequential-estimation caveat

This reference protocol uses group-sequential statistics for the **decision**. Naive effect estimates observed at an early stopping boundary can be biased.

Do not present the stopping-look point estimate as an unbiased final effect estimate merely because the decision was statistically valid. If post-selection effect reporting matters, add a validated sequentially adjusted estimator or a separately protected estimation sample/protocol.

## What this stage does not claim

This module intentionally does not claim to solve every sequential causal problem.

It does not yet implement:

- exact multivariate-normal Lan-DeMets boundaries;
- online-refit CUPED;
- doubly robust time-uniform confidence sequences;
- censoring/survival models for partially observed outcomes;
- event-level repeated-measures inference;
- network interference;
- covariate-adaptive treatment assignment.

Those methods are valuable, but each changes the assumptions enough to deserve its own pre-registered protocol identity and dedicated simulation/evidence suite.

## Recommended operating path

```text
locked offline promotion artifact
    -> register high-power canary plan
    -> freeze CUPED/reference fingerprint
    -> start tiny randomized traffic
    -> continuous anytime-valid guardrails
    -> staged safety advancement
    -> final rollout stage
    -> planned group-sequential primary looks
    -> promote OR rollback
```

If a credible expected final-stage sample size cannot be specified, use the original always-valid promotion path rather than inventing a maximum after looking at the data.
