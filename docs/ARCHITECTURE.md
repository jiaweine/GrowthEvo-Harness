# GrowthEvo Runtime Architecture

## 1. Responsibility boundaries

GrowthEvo separates causal estimation, semantic planning, numeric policy improvement, execution safety, process credit, policy evaluation and promotion.

```text
Logged / randomized growth data
  -> Cross-Fitted DR-Learner
  -> CATE Serving Bridge
  -> Causal Belief

Growth Goal + Causal Belief
  -> Hypothesis Planner
  -> Hierarchical Numeric Policy
  -> Support-Anchored Policy Improvement
  -> Legal Action Gate
  -> Tool / Channel Execution
  -> Environment Observation
      -> GrowthPRM step credit
      -> Planner trajectory export
      -> Delayed business outcome
  -> Causal Reward
  -> IPS / DR / beta*-IPS + overlap diagnostics
  -> Split-Conformal Calibration
  -> Counterfactual Verifier
  -> Replay / Stress / Shadow / Promotion
  -> Failure-Driven Harness Evolution
```

The separation is deliberate:

- causal estimators infer incrementality from logged evidence;
- the planner proposes growth intent and information acquisition;
- the numeric policy chooses channel, offer, timing and budget parameters;
- conservative improvement cannot jump freely outside behavior-policy support;
- the legal gate is non-learnable and executes before side effects;
- GrowthPRM scores intermediate progress without redefining the business metric;
- the Verifier judges logged/experimental evidence and constraints, not planner prose;
- the Evolver can propose bounded changes but cannot promote itself or rewrite the Verifier.

## 2. Causal learning path

`LoggedTreatmentRecord` stores the full logging-policy propensity vector. For treatment `a` versus `NO_TREATMENT`, propensities are renormalized within the pair before AIPW pseudo-outcome construction.

`CrossFittedDRLearner` then:

1. deterministically assigns treatment/control rows to stratified folds;
2. trains treatment and control outcome models on K-1 folds;
3. generates held-out doubly-robust pseudo-outcomes;
4. trains the second-stage effect model only on out-of-fold pseudo-outcomes;
5. records overlap coverage and residual scale;
6. tracks extrapolation distance at serving time.

The reference learner uses a dependency-free ridge model so CI can test the full causal pipeline. Heavy CATE libraries remain adapters rather than Runtime dependencies.

## 3. CATE serving path

`CausalUpliftServingBridge` maps fitted per-channel treatment-effect models into the `UserObservation` contract:

```text
channel_uplift
uplift_uncertainty
```

It also exposes channel-level support and uncertainty for diagnostics. Unsupported extrapolation increases uncertainty instead of silently turning into a confident zero.

`natural_conversion` remains separate from treatment uplift at every layer.

## 4. Causal belief state

`CausalBelief` separates natural outcome probability from treatment-effect estimates:

```text
natural_conversion = P(Y=1 | no treatment, x)
channel_uplift[a]   = E[Y(a) - Y(no treatment) | x]
```

The belief also carries uplift uncertainty, LTV, fatigue, churn risk, touch counts, spend, lifecycle state and consented channels.

## 5. Hierarchical decision contract

The high-level option policy chooses one of:

```text
ACQUIRE
ACTIVATE
RETAIN
REACTIVATE
UPSELL
EXPLORE
HOLDOUT
STOP
```

The low-level policy chooses channel, creative, send time, offer value, expected direct budget, frequency cost, expected uplift and uncertainty.

`NO_TREATMENT` is a first-class channel with exactly zero treatment uplift, zero budget and zero touch cost.

## 6. Support-anchored policy improvement

`SupportAnchoredPolicyImprover` takes discrete action value/cost estimates plus the behavior-policy distribution.

It excludes unsupported treatment actions, computes pessimistic value lower bounds and interpolates toward the best supported action under a total-variation cap:

\[
\pi_{new}=(1-\eta)\mu+\eta\delta_{a^*}.
\]

An expected-cost cap can shrink `η` further. If the behavior policy itself breaches a configured hard cost limit, the module can fall back to `NO_TREATMENT`.

This is an offline improvement guard, not the final promotion gate.

## 7. Legal action gate

The gate runs before treatment execution and enforces consent, total budget, offer cap, fatigue, churn risk and 24h/7d frequency caps.

A blocked treatment is never replaced by another treatment in the same decision step. Runtime falls back to `HOLDOUT / NO_TREATMENT`.

## 8. Cost accounting

`GrowthAction.budget` is the complete expected direct cost of an action. If an offer has expected economic cost, the policy compiler includes it in `budget`; the world model does not charge it again.

## 9. Event sourcing

Important decisions are appended to a hash-chained event stream:

```text
GOAL_COMPILED
BELIEF_UPDATED
HYPOTHESIS_PLANNED
ACTION_PROPOSED
ACTION_ALLOWED / ACTION_BLOCKED
FEEDBACK_OBSERVED
REWARD_ASSIGNED
PROCESS_REWARD_ASSIGNED
ROLLOUT_EVALUATED
VERIFICATION_COMPLETED
FAILURE_CLASSIFIED
PATCH_PROPOSED
```

A durable backend can replace the in-memory store, but append-only ordering and event semantics should remain stable.

## 10. GrowthPRM and planner training path

`GrowthProcessRewardModel` scores planner/tool steps using potential change, evidence gain, action confidence, tool success/failure, direct cost, duplicate evidence and irreversible side effects.

`TrajectoryTrainerAdapter` converts event-derived transitions into backend-neutral Agent-RL training records with:

```text
observation
action
reward
value estimate
next value estimate
legal-action flag
tool-success flag
done
credit boundary
```

It computes GAE and supports `credit_boundary` resets across rollback, environment reset, user/segment switch and delayed-outcome attribution boundaries. This prevents local credit from leaking through known dynamics discontinuities.

The export is intentionally trainer-neutral; external PPO/GRPO systems can consume it without taking ownership of Runtime facts or safety semantics.

## 11. OPE and support diagnostics

Single user interactions are not sufficient causal evidence for policy promotion.

Logged policy evaluation uses IPS, Doubly-Robust, estimated beta*-IPS, estimator standard errors, ESS/ESS ratio, support coverage, maximum importance weight and weight coefficient of variation.

Weak overlap yields `INSUFFICIENT_EVIDENCE`, not a fake win or fake failure.

## 12. Split-conformal calibration

`ConformalPolicyCalibrator` fits one-sided residual margins from matured cohorts. Margin fields are named explicitly (`value_lower_margin`, `spend_upper_margin`, etc.); actual bounds are created only when a margin is applied to a new prediction.

Calibration can only make promotion more conservative.

## 13. Counterfactual verification lifecycle

```text
interaction events
    -> logged behavior-policy cohort
    -> OPE + overlap diagnostics
    -> statistical uncertainty
    -> optional conformal calibration
    -> business constraint aggregates
    -> CounterfactualVerifier
```

Verifier outcomes are `PASS`, `FAIL` and `INSUFFICIENT_EVIDENCE`.

## 14. GrowthAgentBench

The built-in benchmark harness uses an auditable synthetic contextual-bandit oracle with heterogeneous treatment effects and context-dependent logging propensities.

It reports held-out CATE RMSE/MAE/bias, serving support/uncertainty, oracle policy value and regret. Synthetic benchmark results are regression evidence only, never product claims.

Public dataset adapters should preserve propensities, action legality, delayed outcomes and holdout semantics.

## 15. Risk-sensitive model-based safety

The simulator is used for stress testing and candidate ranking, not final causal promotion. Long-horizon rollout updates fatigue, churn risk, spend, touch counts, intent and effective uplift.

Stress scenarios can lower uplift, inflate cost and amplify fatigue. Candidate ranking uses:

\[
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation).
\]

## 16. Two-timescale learning

### Fast loop

The growth policy adapts treatment decisions from causal state and logged outcomes. The repository now contains a reference CATE learner and support-anchored contextual policy-improvement kernel; neural sequential IQL/CQL remains an external training backend.

### Slow loop

Harness evolution updates whitelisted planner, feature, memory, tool, delegation, exploration and reward-shaping coordinates from verified failure traces.

Frozen coordinates remain North-Star metric, consent semantics, budget ledger, event store, Verifier, deployment gate and no-treatment semantics.

## 17. Production extension points

Production systems can replace:

- EventStore with Postgres/Kafka/event-log storage;
- GrowthHypothesisPlanner with an LLM or trained planner;
- reference ridge CATE models with CausalML/EconML/neural uplift;
- support-anchored contextual improvement with sequential offline-RL training;
- UserWorldModel with a calibrated learned digital twin;
- ToolRegistry with MCP / CRM / Ads adapters;
- trainer export consumer with verl / Agent Lightning-style execution-training separation.

The frozen decision, consent, constraint, event and verification contracts should remain owned by GrowthEvo across those replacements.
