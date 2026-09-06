# Safe Online Promotion and Canary Protocol

GrowthEvo treats online rollout as an additional evidence layer after locked offline causal evaluation. A model+harness candidate does **not** receive production authority merely because it won validation or passed a final offline holdout.

The intended lifecycle is:

```text
locked validation
    -> frozen winner
    -> deferred one-shot causal holdout
    -> promotion-eligible artifact
    -> tiny randomized canary
    -> staged non-inferiority checks
    -> final-stage superiority check
    -> champion promotion or automatic rollback
```

The original deterministic GrowthEvo policy remains the champion until the final online gate passes.

## Why the online layer is separate

The offline verifier answers whether a frozen policy has credible causal value and support in historical or randomized evidence. The online canary answers a different question: whether that already-qualified candidate remains safe under live traffic, live systems, current user mix, and operational constraints.

This mirrors modern progressive-delivery systems: expose a small fraction first, continuously monitor guardrails, and expand only when the evidence supports doing so. It also avoids using ordinary fixed-horizon confidence intervals for repeated peeking.

## Candidate provenance

`CanaryCandidate.from_locked_artifact(...)` accepts only an artifact with `promotion_eligible=True`. The candidate binds:

- selected model+harness name;
- provider and pinned model snapshot;
- harness contract fingerprint;
- source code commit;
- locked holdout fingerprint;
- causal evidence-manifest fingerprint;
- a SHA-256 fingerprint of the complete promotion artifact.

A canary plan must reference the exact candidate contract and promotion-artifact fingerprint. A different prompt, critic, threshold, model snapshot, holdout, or evidence manifest is therefore a different online challenger.

## Stable staged routing

`CanaryRouter` uses two independent deterministic hashes:

1. an inclusion hash decides whether an analysis unit is in the current traffic stage;
2. an arm hash decides champion versus challenger inside the canary.

Because inclusion is compared with an increasing stage threshold, a unit admitted at 1% remains admitted at 5%, 10%, and later stages. The arm hash is independent of stage, so already-exposed units are never reshuffled between champion and challenger.

`OnlinePromotionController` recomputes the route when a matured outcome arrives. It rejects:

- units not admitted by the current stage;
- forged or mismatched arm assignments;
- mismatched treatment probabilities;
- outcomes tagged with the wrong traffic stage.

This is important for causal integrity: logged assignment is evidence, not metadata that callers may rewrite after the fact.

## Analysis-unit contract

Each `CanaryObservation` represents one unique randomized **analysis unit** with one matured bounded outcome vector. The monitor stores only a BLAKE2 hash token for deduplication, not the raw analysis-unit ID.

Repeated observations from the same user must not be submitted as independent units. If the experiment randomizes by user and produces many events per user, aggregate those events upstream into one bounded user-level outcome for the analysis window, or use a separately validated cluster/sequential method.

Similarly, delayed metrics should enter the canary only after their predefined maturity window. Do not mix partially observed and fully matured outcomes without a protocol designed for censoring or delayed feedback.

## Bounded randomized contrasts

For a challenger assignment probability `p` and bounded metric outcome `Y`, the reference monitor uses the Horvitz-Thompson difference contribution

```text
X = A * Y / p - (1 - A) * Y / (1 - p)
```

where `A=1` is challenger and `A=0` is champion.

For metrics where lower is better, GrowthEvo multiplies this contrast by `-1`, so every monitored relative contrast has the same interpretation:

```text
positive = challenger better
negative = challenger worse
```

Outcome bounds are pre-registered in `CanaryMetricSpec`. An observation outside those bounds is rejected rather than silently clipped.

## Anytime-valid e-process

GrowthEvo's reference sequential gate uses a mixture of bounded-mean Hoeffding e-processes.

For an observation `X_t` in `[a_t, b_t]` and the one-sided null

```text
E[X_t | F_(t-1)] <= mu_t,
```

each fixed positive bet `eta` uses the component

```text
exp(sum_t eta * (X_t - mu_t) / (b_t - a_t) - eta^2 / 8).
```

The pre-registered convex mixture of these components is also an e-process. This permits continuous monitoring and optional stopping without pretending that a fixed-horizon z/t test remains valid after repeated peeking.

The implementation is intentionally a conservative reference protocol. It assumes the randomized analysis-unit sequence and bounded conditional-mean null are appropriate. It is **not** a drop-in proof for arbitrary repeated-user, network-interference, adaptive-outcome, heavy-tail, or delayed-censoring settings.

## Three different sequential questions

The canary deliberately separates three decisions.

### 1. Harm / rollback

For every metric, the monitor tests for evidence that the challenger is worse than its pre-registered non-inferiority margin. Optional absolute minimum/maximum challenger constraints are monitored too.

Rollback uses the maximum e-value seen over time. Because rollback fires if **any** harm process crosses, `rollback_family_alpha` is Bonferroni-allocated across the relative and absolute harm processes.

A deterministic cumulative challenger cost cap is an additional kill switch and does not wait for statistical evidence.

### 2. Safe-to-ramp

Traffic moves from one stage to the next only after:

- the stage has received the minimum number of new matured analysis units;
- every relative metric has current sequential evidence of non-inferiority;
- every declared absolute guardrail has current sequential evidence of safety;
- no harm or deterministic cost gate has fired.

This is an intersection safety claim: all declared constraints must pass. A strong primary metric cannot compensate for a failed fatigue, churn, cost, latency, or other guardrail.

### 3. Final promotion

Primary superiority evidence is deliberately **not accumulated before the final traffic stage**. Once the challenger reaches the final stage, a fresh primary e-process tests whether the incremental primary effect exceeds `primary_min_improvement`.

The candidate becomes champion only when:

- all safety/non-inferiority gates pass at the final stage; and
- final-stage primary superiority crosses the pre-registered promotion threshold.

Until then, the original champion remains authoritative.

## Absolute guardrails

A metric may declare `absolute_min` and/or `absolute_max` in addition to relative non-inferiority. These are challenger-arm mean constraints.

Examples:

- fatigue <= 0.60;
- churn risk <= 0.30;
- error rate <= 0.01;
- successful-completion rate >= 0.98.

Both directions are monitored: evidence can establish safety for stage advancement, while independent opposite-direction evidence can trigger rollback.

## Champion-challenger audit chain

`OnlinePromotionController` keeps a small append-only SHA-256 hash chain for control-plane transitions:

- challenger registered;
- canary started;
- stage advanced;
- challenger rolled back; or
- challenger promoted.

Audit records contain aggregate sequential evidence and provenance fingerprints, not raw analysis-unit IDs or per-user outcomes. The original runtime event schema is unchanged.

## Recommended rollout posture

A representative plan might use stages such as:

```text
1% -> 5% -> 10% -> 25%
```

but the correct stages, margins, outcome bounds, maturity windows, and sample requirements must be pre-registered for the actual product and risk profile. High-severity actions should use smaller initial exposure and stricter guardrails.

Do not interpret a canary as permission to skip experimentation design. The assignment unit, assignment probability, eligibility population, metric definitions, outcome bounds, delayed-feedback window, interference assumptions, and rollback limits are part of the causal protocol.

## Relationship to current industry practice

The design intentionally borrows production patterns rather than a particular vendor implementation:

- Netflix has published production work on sequential / anytime-valid canary and regression experiments and design-based confidence sequences.
- Uber has described staged rollout with continuous sequential regression detection and automatic risk reduction at low exposure.
- Spotify Confidence distinguishes fixed/group-sequential experimentation from always-valid continuous monitoring and uses sequential deterioration checks for rollouts.
- Google SRE and Google Cloud describe multi-stage canarying with control-vs-canary metrics, verification gates, and automated advancement/rollback.

GrowthEvo adds its own requirement on top: an LLM challenger must first carry locked causal provenance, and final online promotion still requires incremental-value evidence rather than model reputation or an LLM-as-a-judge score.

## Future research extensions

The current mixture e-process is deliberately dependency-free and auditable. Higher-power future protocols can be added behind a typed preregistered interface, for example:

- group-sequential tests when a credible expected sample size is known;
- regression-adjusted anytime-valid inference / variance reduction;
- design-based confidence sequences for richer randomization designs;
- cluster-aware sequential inference for repeated-user outcomes;
- delayed-outcome and survival-aware sequential estimators;
- covariate-adaptive randomization with logged predictable propensities.

Such methods should be new protocol identities, not silent changes under an existing canary-plan fingerprint.
