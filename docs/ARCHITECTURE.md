# GrowthEvo Runtime Architecture

## 1. Responsibility boundaries

GrowthEvo separates semantic planning, numeric policy optimization, execution safety, process credit, causal evaluation and policy promotion.

```text
Growth Goal
  -> Causal Belief
  -> Hypothesis Planner
  -> Hierarchical Numeric Policy
  -> Legal Action Gate
  -> Tool / Channel Execution
  -> Environment Observation
      -> GrowthPRM step credit
      -> Delayed business outcome
  -> Causal Reward
  -> IPS / DR / β*-IPS + overlap diagnostics
  -> Split-Conformal Calibration
  -> Counterfactual Verifier
  -> Replay / Stress / Shadow / Promotion
  -> Failure-Driven Harness Evolution
```

The separation is deliberate:

- The planner proposes the growth intent and information plan.
- The numeric policy chooses channel, offer, timing and budget parameters.
- The legal gate is non-learnable and executes before side effects.
- GrowthPRM scores intermediate progress without redefining the final business metric.
- OPE evaluates a candidate from logged behavior-policy evidence.
- The verifier judges evidence and hard constraints, not planner prose.
- The evolver can propose bounded changes but cannot promote itself or rewrite the verifier.

## 2. Causal belief state

`CausalBelief` separates natural outcome probability from treatment-effect estimates:

```text
natural_conversion = P(Y=1 | no treatment, x)
channel_uplift[a]   = E[Y(a) - Y(no treatment) | x]
```

These quantities are never interchangeable. A high natural conversion rate is not evidence that a treatment is incrementally useful.

The belief also carries:

- uplift uncertainty;
- lifetime value;
- fatigue and churn risk;
- 24-hour and 7-day touch counts;
- spend-to-date;
- lifecycle state;
- consented channels.

A production reducer can replace `build_causal_belief()` with a learned state encoder while preserving the same contract.

## 3. Hierarchical decision contract

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

The low-level policy chooses:

```text
channel
creative
send time
offer value
expected direct budget
frequency cost
expected uplift
uncertainty
```

`NO_TREATMENT` is a first-class channel with exactly zero treatment uplift, zero budget and zero touch cost.

## 4. Legal action gate

The gate runs before treatment execution and enforces:

- channel consent;
- total budget;
- offer cap;
- fatigue limit;
- churn-risk limit;
- 24-hour frequency cap;
- 7-day frequency cap.

A blocked treatment is never replaced by another treatment in the same decision step. The runtime falls back to `HOLDOUT / NO_TREATMENT`. This prevents a learned policy from searching around a hard constraint after rejection.

## 5. Cost accounting

`GrowthAction.budget` is the complete expected direct cost of an action.

If an offer has expected economic cost, the policy compiler includes it in `budget`. The world model does not charge the offer a second time. `offer_value` remains separate because face value and expected economic cost are not generally identical.

This contract avoids double counting in reward, ROI and budget checks.

## 6. Event sourcing

Every important decision is appended to a hash-chained event stream.

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

Each event hash covers sequence number, event type, UTC timestamp, normalized payload and the previous event hash. A durable backend can replace the in-memory store, but append-only ordering and event semantics should remain stable.

## 7. GrowthPRM process-credit path

Long-horizon outcomes are sparse, so the planner needs intermediate credit without letting shaping replace the North-Star metric.

`GrowthProcessRewardModel` scores each planner/tool step using:

- potential change in Goal Progress / Evidence Quality / Constraint Slack;
- evidence gain from the resulting observation;
- confidence of the preceding action;
- tool success/failure;
- direct cost;
- duplicate-evidence penalty;
- irreversible-side-effect penalty.

Trajectory output explicitly separates:

```text
process_total
terminal_outcome
total = process_total + terminal_outcome
```

This distinction is important for Agent-RL training and for debugging reward hacking.

## 8. OPE and support diagnostics

Single user interactions are not sufficient causal evidence for policy promotion. Runtime execution and cohort verification are separate phases.

Logged policy evaluation uses:

- IPS;
- Doubly-Robust estimation;
- estimated β*-IPS additive control variate;
- estimator-specific standard error;
- effective sample size and ESS ratio;
- practical support coverage;
- maximum importance weight;
- importance-weight coefficient of variation.

A candidate with weak logging-policy overlap is classified as `INSUFFICIENT_EVIDENCE`, not as a failed policy.

## 9. Split-conformal calibration

`ConformalPolicyCalibrator` fits one-sided **residual margins** from matured policy cohorts.

The dataclass fields are explicitly named:

```text
value_lower_margin
roi_lower_margin
spend_upper_margin
fatigue_upper_margin
churn_risk_upper_margin
```

They are not absolute bounds. Bounds are constructed only when a margin is applied to a new prediction through methods such as `value_lcb()` or `spend_ucb()`.

The verifier combines statistical and calibrated evidence conservatively. Calibration cannot make a candidate easier to promote.

## 10. Counterfactual verification lifecycle

```text
interaction events
    -> logged behavior-policy cohort
    -> OPE + overlap diagnostics
    -> statistical uncertainty
    -> optional conformal calibration
    -> business constraint aggregates
    -> CounterfactualVerifier
```

Verifier outcomes are:

- `PASS` — enough evidence and all value/risk bounds pass;
- `FAIL` — enough evidence, but value or a hard constraint fails;
- `INSUFFICIENT_EVIDENCE` — sample size, ESS, support or weight tails are not trustworthy enough.

Lack of evidence is not evidence of harm.

## 11. Risk-sensitive model-based safety

The simulator is used for stress testing and candidate ranking, not for final causal promotion.

Long-horizon rollout updates:

- fatigue;
- churn risk;
- spend;
- touch counts;
- intent / baseline conversion;
- effective treatment uplift.

Stress scenarios can lower uplift, inflate cost and amplify fatigue. `RiskSensitiveMPC` evaluates candidates over multiple stochastic seeds and ranks them by:

\[
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation)
\]

Synthetic return never replaces logged/experimental evidence in the promotion gate.

## 12. Two-timescale learning

### Fast loop

The growth policy adapts treatment decisions from causal state and logged outcomes. Candidate learned backends include contextual bandits, uplift policy learning, constrained IQL/CQL and low-latency policy distillation.

### Slow loop

Harness evolution updates selected cognitive coordinates from verified failures.

Allowed coordinates:

- planner hypothesis template;
- feature routing;
- memory retrieval policy;
- tool routing;
- delegation strategy;
- exploration coefficient;
- short-horizon reward shaping.

Frozen coordinates:

- North-Star metric;
- consent semantics;
- budget ledger;
- event store;
- verifier;
- deployment gate;
- no-treatment semantics.

A patch is only a proposal. It must pass replay/stress and later shadow evaluation before promotion.

## 13. Production extension points

The core stays dependency-light. Production systems can replace:

- EventStore with Postgres/Kafka/event-log storage;
- GrowthHypothesisPlanner with an LLM or trained planner;
- HierarchicalGrowthPolicy with an offline/constrained RL policy;
- CATE features with CausalML/EconML or custom estimators;
- UserWorldModel with a calibrated learned digital twin;
- ToolRegistry with MCP / CRM / Ads adapters;
- trainer layer with verl / Agent Lightning-style execution-training separation.

The frozen decision, consent, constraint, event and verification contracts should remain owned by GrowthEvo across those replacements.
