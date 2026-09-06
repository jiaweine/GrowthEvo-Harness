# Robust Sequential Stress Lab

The Sequential Evidence Lab checks nominal operating characteristics under a frozen bounded Bernoulli DGP. This document defines the adversarial layer above it.

The goal is not to make every protocol look robust. The goal is to make failure modes reproducible, typed, fingerprinted, and impossible to hide behind an aggregate success metric.

## Principle

Software CI and statistical robustness are different assertions.

A test can pass because GrowthEvo correctly reproduces a known failure mode. The resulting `SequentialStressArtifact` may still have `robust_ready=false`. That is intentional.

The current online controllers remain unchanged. The stress lab is a research and governance layer, not a silent production-policy rewrite.

## Six adversarial DGP families

### 1. Clustered repeated events

`ClusterRepeatedEventStress` deliberately emulates an invalid analytics pipeline that treats repeated correlated events from one randomized cluster as if they were independent analysis units.

The current GrowthEvo online contract already says one randomized analysis cluster contributes one matured bounded outcome vector. The stress lab nevertheless attacks the implementation assumption because an upstream pipeline can fabricate distinct event IDs and thereby evade simple deduplication.

The artifact reports group-sequential and anytime false-positive behavior but always records the analysis-unit contract violation. A future cluster-aware backend should model cluster-level influence directly or consume one pre-aggregated cluster outcome.

### 2. Delayed / informative censoring

`DelayedCensoringStress` generates arm- and outcome-dependent missingness. This is different from ordinary delayed maturation.

Exposure tickets solve *which stage an eventual outcome belongs to*. They do not identify the causal estimand when outcomes are differentially missing by treatment arm or by latent outcome.

The stress result records missingness by arm and marks informative censoring as a blocker. A future mitigation needs an explicit missingness/censoring model, inverse-probability-of-observation weighting, survival estimand, or another preregistered identification strategy. Silent complete-case analysis is not accepted as a fix.

### 3. Sample Ratio Mismatch / assignment integrity

`SRMStress` corrupts the observed treatment/control ratio through differential logging.

GrowthEvo performs a chi-square-equivalent two-arm goodness-of-fit check. For one degree of freedom the survival probability is computed as `erfc(sqrt(chi2 / 2))`, so the reference implementation remains dependency-free.

This follows the operational lesson used by mature experimentation systems such as Microsoft ExP: an experiment with an unexplained SRM is not trustworthy enough for effect interpretation. A large positive treatment estimate does not override an assignment-integrity failure.

References:

- Microsoft Research, *Diagnosing Sample Ratio Mismatch in A/B Testing*.
- Microsoft Research, *Alerting in Microsoft’s Experimentation Platform (ExP)*.
- Microsoft PlayFab experimentation best practices, SRM section.

### 4. Heavy tails / bound violations

The current online e-process and high-power primary monitor rely on preregistered bounded outcomes. `HeavyTailStress` intentionally generates Pareto observations outside those bounds.

The correct reference behavior is rejection, not clipping. Clipping or winsorization changes the estimand and must therefore be separately preregistered and fingerprinted.

The stress artifact records both the out-of-bound rate and the conditional rejection rate. `fail_closed=true` means every generated out-of-contract value was rejected before statistical state mutation.

### 5. Heterogeneous treatment effects

`HeterogeneousEffectStress` creates a harmed subgroup and a benefited subgroup. Aggregate average treatment effect can be positive even while a substantial subgroup is harmed.

The current aggregate primary-success protocol does not contain a subgroup-safety theorem. The stress artifact therefore marks hidden subgroup harm as a blocker regardless of whether the aggregate test promotes.

A future mitigation must preregister protected or product-critical subgroup guardrails, hierarchical multiplicity control, or another validated heterogeneous-effect safety policy. Post-hoc subgroup mining cannot retroactively authorize promotion.

### 6. Nonstationary sign reversal

`NonstationaryEffectStress` creates an early positive treatment effect followed by a later negative effect. It records how often group-sequential or anytime success occurs during the positive phase before the sign reversal is visible.

This is not a violation of a stationary-null Type-I theorem; it is an estimand and deployment-risk problem. A protocol designed to detect an early average effect may legitimately stop early while the long-run effect later reverses.

A future mitigation can bind a minimum maturity window, long-horizon estimand, delayed guardrail, global holdout, or time-indexed treatment-effect stability requirement into the promotion contract.

## Artifact and identity

`SequentialStressSuitePlan` fingerprints:

- the exact `HighPowerCanaryPlan`;
- replication count and root seed;
- the six typed stress specifications;
- the control event rate.

Each stress family receives a deterministic derived RNG stream. Re-running the same implementation, plan, seed, and commit yields the same artifact.

`SequentialStressArtifact` binds the commit, high-power plan, stress-plan identity, all six result objects, the blocker list, and the `robust_ready` verdict.

## Robust certificate

`RobustSequentialProtocolCertificate` is a future admission credential that requires both:

1. a nominal `SequentialProtocolCertificate` from the Evidence Lab; and
2. a `SequentialStressArtifact` with no unresolved blockers.

It also requires the nominal and stress artifacts to target the same source commit and the same high-power plan fingerprint.

The certificate is **not** consumed by the current production controller. This avoids circular self-authorization while the stress suite is still revealing gaps.

## Expected posture of the current protocol

The current reference protocol is expected to fail `robust_ready` under at least these attacks:

- event-level pseudoreplication across repeated randomized clusters;
- informative arm/outcome-dependent censoring;
- hidden subgroup harm behind an aggregate positive effect;
- some nonstationary sign-reversal regimes.

By contrast, it should contain or detect:

- out-of-bound heavy-tailed observations through fail-closed input validation;
- sufficiently strong sample-ratio corruption through the SRM diagnostic.

That distinction is useful. It tells us what should be fixed in data integrity, what needs a new estimator, and what needs a different causal estimand.

## What comes after stress discovery

Do not add a sophisticated estimator merely because it is fashionable. Add it only against a demonstrated blocker and then rerun both nominal and adversarial operating-characteristic studies.

Likely follow-on research paths are:

- cluster-robust or cluster-level sequential inference;
- delayed/censored-outcome estimators with explicit identification assumptions;
- exact numerical group-sequential boundaries;
- doubly robust anytime-valid ATE confidence sequences;
- subgroup-safe multiplicity control;
- long-horizon/global-holdout checks for effect reversal and novelty decay.

Any such backend gets a new protocol identity and must re-earn nominal and stress qualification.
