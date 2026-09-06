# Outcome maturity and censoring contract

GrowthEvo already records the stage at which a user was exposed so a delayed outcome can be attributed to the correct rollout stage. That solves **stage provenance**. It does not solve a different problem:

> when is an endpoint mature enough that its absence can be interpreted, and when is the analysis population complete enough for a complete-case causal analysis?

This module makes that distinction explicit before any more sophisticated censoring estimator is introduced.

## Design posture

The v1 rule is deliberately strict:

> complete-case promotion authority exists only after enrollment is frozen, the entire frozen cohort has completed the preregistered follow-up horizon plus ingestion grace, and every endpoint has arrived on time.

If any frozen endpoint is still pending, delayed in the pipeline, or missing after the cutoff, GrowthEvo does **not** silently drop that unit and continue with complete cases.

This is a governance contract, not a claim that complete-case analysis is generally optimal. Its purpose is to prevent an invalid complete-case estimand from being used by accident.

## Why this is separate from SRM

Sample Ratio Mismatch is an important experiment-integrity diagnostic, but the absence of SRM does not imply that missing outcomes are ignorable.

Two arms can retain the expected 50/50 composition while missingness still depends on baseline risk, latent outcome, device state, geography, or another variable that biases the observed endpoint distribution. Conversely, an arm-level maturity imbalance can create matured-population SRM and should block interpretation immediately.

The integrity gate therefore answers:

> is the observed treatment/control composition trustworthy?

The maturity ledger answers:

> has the frozen endpoint cohort completed its declared follow-up contract, and are all endpoints present for the complete-case estimand?

Neither question substitutes for the other.

Microsoft's experimentation guidance makes the same operational distinction between data-quality checks, missing telemetry, data loss, join quality, and latency. Analyses built on incomplete or imbalanced telemetry are not considered trustworthy until the data issue is understood.

## OutcomeMaturitySpec

`OutcomeMaturitySpec` freezes:

- endpoint name;
- endpoint maturity delay;
- ingestion grace window;
- clock contract.

For exposure time `t0`:

`maturity_at = t0 + maturity_delay`

and

`accept_until = maturity_at + ingestion_grace`.

Changing the endpoint, delay, grace, or clock contract creates a different versioned fingerprint.

The maturity delay is the causal/measurement window. The ingestion grace is only an engineering allowance for a matured endpoint to become available in the analysis store. Extending either after seeing interim results changes the analysis protocol and is not allowed under the same fingerprint.

## Pipeline participants

Suppose enrollment stops at day 10, but the primary endpoint is day-7 value. A user exposed late on day 10 still has almost seven days of follow-up remaining.

That user is a **pipeline participant**. Enrollment being closed does not make the endpoint mature.

`OutcomeMaturityLedger.required_ready_at` is the latest preregistered `accept_until` among all frozen analysis units. A complete-case seal cannot be issued before this point, even if every earlier participant already has an endpoint.

This avoids the common error:

`last user enrolled -> experiment stopped -> analyze immediately`

when the endpoint itself requires additional follow-up.

## Explicit follow-up states

Every frozen analysis unit is classified at an analysis timestamp as one of:

- `pending_followup` — the endpoint window itself is not mature yet;
- `awaiting_ingestion` — the endpoint is mature but still inside the frozen ingestion grace period;
- `matured_on_time` — the endpoint was accepted inside the frozen window;
- `overdue_missing` — the endpoint did not arrive by the preregistered cutoff.

These states are intentionally not collapsed into a generic `missing` flag. Administrative delay and unresolved censoring are different conditions.

## Frozen cohort and complete-case authority

`close_enrollment()` freezes the analysis cohort. New exposure registrations are rejected afterward.

`seal_complete_case_analysis()` requires all of the following:

1. enrollment is closed;
2. the analysis cohort is non-empty;
3. the latest frozen follow-up plus ingestion grace has elapsed;
4. no pipeline participant is still awaiting endpoint maturity;
5. no matured endpoint is still inside the ingestion pipeline grace window;
6. no endpoint is missing after its preregistered cutoff;
7. every frozen unit has one accepted endpoint receipt.

Only then can `CompleteCaseMaturitySeal` be issued.

The seal binds:

- endpoint and maturity-spec fingerprint;
- tokenized frozen cohort fingerprint;
- enrollment-close time;
- analysis-as-of time;
- arm counts;
- complete endpoint count.

After sealing, the ledger is read-only.

## Late outcomes are not used to move the goalposts

An endpoint arriving after `accept_until` is rejected by the v1 complete-case contract.

GrowthEvo does not respond by silently extending the cutoff until the desired data eventually appears. Such an extension would change who is considered observed and could become outcome-dependent.

If a product genuinely needs a longer ingestion allowance, that window should be chosen before analysis and given a new maturity-spec fingerprint.

A late endpoint can still be retained by an upstream raw-data system for another explicitly defined estimand. It simply cannot retroactively authorize the frozen complete-case protocol.

## Administrative censoring versus informative censoring

A complete follow-up window can solve **administrative censoring** caused by analyzing before the endpoint has had time to mature.

It does not prove that any remaining missingness is random.

If endpoints remain missing after the frozen cutoff, complete-case promotion authority fails closed. A future estimator may use incomplete outcomes only if it declares and validates a different identification strategy, for example:

- inverse probability of censoring / observation weighting;
- survival or time-to-event estimands;
- doubly robust longitudinal estimation;
- targeted-learning procedures for delayed outcomes;
- sensitivity analysis under explicit missing-not-at-random assumptions.

Such a method must carry its own nuisance-model contract, positivity/support checks, fitting/evaluation split, protocol fingerprint, and Evidence/Stress-Lab qualification. It must not reuse `CompleteCaseMaturitySeal` as if the cohort were complete.

## Relationship to HighPowerExposureTicket

The two tickets solve different problems.

`HighPowerExposureTicket` freezes:

- rollout stage;
- arm;
- traffic fraction;
- propensity.

`OutcomeMaturityTicket` freezes:

- endpoint horizon;
- exposure time;
- maturity time;
- ingestion cutoff;
- endpoint-contract identity.

A production integration can bind both to the same randomized analysis unit, but neither replaces the other.

Stage provenance answers **where the outcome belongs**. Maturity provenance answers **when the endpoint is eligible to exist and when absence becomes a censoring problem**.

## Receipt integrity and privacy

The ledger stores an experiment-scoped 16-byte BLAKE2 token instead of the raw analysis-unit ID.

Accepted outcomes are represented only by an externally supplied `outcome_fingerprint`; the ledger does not persist raw outcome values. Replaying the exact same receipt is idempotent. Changing the timestamp or outcome fingerprint after first acceptance is rejected as tampering.

The ledger has an independent append-only SHA-256 audit chain for:

- maturity-contract registration;
- enrollment closure;
- complete-case sealing.

Raw analysis-unit IDs and raw outcomes are excluded from audit payloads.

## What this phase does not claim

The v1 maturity contract does not itself estimate a treatment effect and does not solve:

- informative censoring;
- competing risks;
- recurrent events;
- time-varying treatment;
- cross-cluster interference;
- nonstationary endpoint definitions;
- arbitrary late-data reconciliation.

It provides a clean prerequisite: either the frozen cohort is genuinely complete for the declared endpoint, or complete-case promotion authority is unavailable.

## Research direction

This contract is intentionally built before adding IPCW, survival TMLE, or another delayed-outcome estimator. The sequence is:

`typed stress DGP -> explicit maturity/censoring contract -> demonstrate remaining identification gap -> add a targeted estimator -> validate operating characteristics`.

That keeps estimator sophistication downstream of a clearly stated causal estimand instead of allowing pipeline behavior to define the estimand implicitly.
