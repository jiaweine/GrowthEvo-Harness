# High-Power Sequential Causal Promotion

This protocol is an **optional** successor to the conservative online-canary success gate. It does not replace GrowthEvo's locked offline evaluation, randomized routing, anytime-valid deterioration monitoring, legal constraints, or rollback path.

The design goal is narrower:

> when a credible final-stage sample size can be pre-registered, use fewer planned success looks and frozen pre-exposure variance reduction to obtain more power without weakening continuous safety monitoring.

The original `OnlinePromotionController` retains its anytime-valid success gate. The advanced path is enabled only by constructing `HighPowerOnlinePromotionController` with a `HighPowerCanaryPlan`.

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

Sample and arm-count limits must be integers. The O'Brien-Fleming-shaped schedule requires `alpha < 0.5` so cumulative spending is monotone. Gaussian upper tails use [`math.erfc`](https://docs.python.org/3/library/math.html#math.erfc) to avoid cancellation from subtracting a CDF near one. A look with zero representable alpha allocation cannot authorize success. Small nonzero standard errors retain their actual scale rather than being treated as deterministic outcomes.

It is **not** presented as an exact Lan-DeMets correlated-boundary implementation. A production platform with a validated numerical statistics stack can add an exact boundary calculator behind a new fingerprinted protocol identity.

## Why a separate protocol identity matters

Changing from always-valid inference to group-sequential inference changes the stopping rule and statistical assumptions. It is therefore not a tuning flag hidden under the old plan.

`HighPowerCanaryPlan.fingerprint` binds:

- the complete base canary plan;
- the group-sequential design;
- the frozen CUPED contract, if used;
- the declared randomization/analysis-unit name.

A change to expected sample size, look schedule, alpha, CUPED coefficient, CUPED centering, source reference data, or analysis unit creates a different plan fingerprint.

The current fingerprint schema is `growthevo.high-power-canary-plan.v3`. It binds first-admitted exposure stages, promotion only at planned looks, the final sample-budget stop, and the numerical testing contract. Earlier v1/v2 controllers therefore do not share this protocol identity even with identical plan parameters.

## Frozen CUPED variance reduction

`FrozenCUPEDSpec` supports pre-exposure variance reduction for the primary metric:

```text
Y_adjusted = Y - theta * (X_pre - center)
```

where `X_pre` is a bounded pre-treatment covariate.

The coefficient `theta`, center, covariate bounds, and source fingerprint must be estimated/frozen from pre-exposure or otherwise independent reference data **before online treatment outcomes are inspected**.

The online controller does not refit CUPED after interim looks. This is intentional. Changing covariate adjustment after seeing interim data can invalidate group-sequential Type-I-error guarantees and can create biased or anti-conservative inference.

If the frozen covariate is missing, non-finite, or outside its pre-registered bounds, the advanced primary analysis fails closed for that observation instead of silently imputing or clipping it.

Both canary paths snapshot caller-owned metric mappings and revalidate every metric before updating deduplication, counters, costs, or safety evidence. The advanced path also snapshots covariates and preflights adjusted values, running moments, and the effect estimate for arithmetic overflow. Rejected observations leave the statistical state unchanged and can be corrected and retried.

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

Call `controller.enroll(unit_id)` (or its `route` alias) before exposure. For an admitted unit, the controller records the first exposure stage under a plan-scoped hashed unit token. Repeated calls return that original assignment receipt, including after a stage advance or outcome maturation. A unit excluded from the canary has no admission record and can first enroll when a later traffic stage includes it.

A matured outcome carries the original `routing_stage_index`. Before statistical state or deduplication changes, the controller requires a registered admission and an exact match to its recorded stage, then recomputes the deterministic route for that stage to verify the arm, traffic fraction, and propensity. Matching a caller-selected stage's route alone does not establish exposure provenance.

A valid old-stage delayed outcome may still update cumulative safety evidence, but it does **not** count toward the current stage's minimum matured-outcome quota and does not enter the final-stage primary group-sequential test unless it was originally exposed in the final stage.

This prevents pipeline outcomes from artificially filling a later-stage quota.

The registry has the same in-memory lifetime as the controller's statistical state. Submit outcomes to the controller that enrolled the units; a new controller rejects unregistered outcomes. The registry stores hashed tokens and stage indices, and the aggregate audit chain contains no raw unit IDs or outcome vectors. Integrations must serialize enrollment and observation calls on the controller. The lower-level monitor is a statistical component and does not verify enrollment; production ingestion uses the controller.

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
- if the newly completed planned primary look crosses its allocated success threshold and all safety gates pass at that look, promote the challenger;
- if an interim look passes primary superiority while safety remains unresolved, continue to the next pre-registered look; later safety evidence alone cannot trigger promotion between looks;
- at the final planned sample count, stop unless the joint primary and safety gate passes. Missing superiority or unresolved safety both retain the original champion.

An early primary crossing does not carry success into a later failed look. `GroupSequentialEvidence.success` describes the most recent look, and each later look spends only its own allocation. The primary monitor accepts no observations after its final planned look.

Budget exhaustion is represented as a fail-closed rollback because the candidate has consumed its pre-registered success budget without earning promotion authority. The controller's terminal state rejects further outcomes and enrollment; it cannot silently extend the experiment while waiting for safety.

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
