# GrowthEvo Runtime Architecture

## 1. Boundary of responsibility

GrowthEvo separates semantic planning, numeric policy optimization, execution safety and policy promotion.

```text
Growth Goal
  -> Causal Belief
  -> Hypothesis Planner
  -> Hierarchical Policy
  -> Legal Action Gate
  -> Tool / Simulator
  -> Delayed Feedback
  -> Causal Reward
  -> OPE / Counterfactual Verifier
  -> Replay / Shadow / Promotion
```

The separation is deliberate:

- The planner may propose *what kind of growth objective to pursue*.
- The policy chooses numeric action parameters.
- The legal gate is non-learnable and executes before side effects.
- The verifier judges candidate policies using logged evidence, not planner prose.
- The evolver can propose bounded patches but cannot promote itself.

## 2. Causal belief state

`CausalBelief` contains both natural outcome probability and treatment-effect estimates.

These fields are not interchangeable:

```text
natural_conversion = P(Y=1 | no treatment, x)
channel_uplift[a] = E[Y(a) - Y(no treatment) | x]
```

The runtime never derives uplift from a single post-treatment conversion.

The belief also carries:

- uplift uncertainty
- lifetime value
- fatigue and churn risk
- short- and medium-window touch counts
- spend-to-date
- lifecycle state
- consented channels

A production reducer can replace `build_causal_belief()` with a learned state encoder while preserving this contract.

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

The low-level action policy chooses:

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

`NO_TREATMENT` is a first-class channel with exactly zero treatment uplift, zero direct budget and zero touch cost.

## 4. Legal action gate

The gate is evaluated before treatment execution. It currently enforces:

- channel consent
- campaign budget
- offer cap
- fatigue limit
- churn-risk limit
- 24-hour frequency cap
- 7-day frequency cap

A blocked treatment is never replaced by another treatment in the same decision step. The reference runtime recovers to `HOLDOUT / NO_TREATMENT`.

This prevents an adaptive policy from searching around a hard constraint after rejection.

## 5. Event sourcing

Every runtime decision is appended to a hash-chained event stream.

The current in-memory backend is intentionally small, but event semantics are stable:

```text
GOAL_COMPILED
BELIEF_UPDATED
HYPOTHESIS_PLANNED
ACTION_PROPOSED
ACTION_ALLOWED
ACTION_BLOCKED
FEEDBACK_OBSERVED
REWARD_ASSIGNED
VERIFICATION_COMPLETED
FAILURE_CLASSIFIED
PATCH_PROPOSED
```

Each event hash covers:

- sequence number
- event type
- UTC timestamp
- normalized payload
- previous event hash

A durable backend should preserve these semantics and append-only ordering.

## 6. Two-timescale learning

### Fast loop

The growth policy adapts treatment decisions from state and logged outcomes.

Candidate backends include:

- contextual Thompson sampling / LinUCB
- uplift policy learning
- IQL / CQL for offline RL
- constrained policy optimization
- policy distillation for low-latency serving

### Slow loop

Harness evolution updates selected cognitive coordinates from verified failure traces.

Allowed coordinates:

- planner hypothesis template
- feature routing
- memory retrieval policy
- tool routing
- delegation strategy
- exploration coefficient
- short-horizon reward shaping

Frozen coordinates:

- North-Star metric
- consent semantics
- budget ledger
- event store
- verifier
- deployment gate
- no-treatment semantics

A candidate patch is only a proposal. Replay and shadow evaluation must occur before promotion.

## 7. Cost accounting

`GrowthAction.budget` is defined as the complete expected direct cost of the action.

If an offer has an expected economic cost, the policy compiler must include it in `budget`. The world model therefore does not add offer cost again. This avoids double counting in reward, ROI and budget constraints.

`offer_value` remains a separate field because face value and expected economic cost are not generally identical.

## 8. Verification lifecycle

Single user interactions do not provide sufficient causal evidence for policy promotion.

The runtime therefore separates execution from cohort verification:

```text
interaction events
    -> logged bandit cohort
    -> IPS / DR OPE
    -> uncertainty estimate
    -> constraint aggregates
    -> CounterfactualVerifier
```

Verifier results are tri-state:

- `PASS`
- `FAIL`
- `INSUFFICIENT_EVIDENCE`

The third state is important. Lack of effective sample size is not evidence that a policy is worse.

## 9. Production extension points

The current repository is a reference kernel. Production versions can replace:

- EventStore with Postgres/Kafka/event-log storage
- GrowthHypothesisPlanner with an LLM or trained planner
- HierarchicalGrowthPolicy with offline/constrained RL
- UserWorldModel with a calibrated user digital twin
- ToolRegistry with MCP/CRM/Ads adapters
- OPE estimators with cross-fitted and self-normalized estimators

The frozen decision, constraint and verification contracts should remain stable across those replacements.
