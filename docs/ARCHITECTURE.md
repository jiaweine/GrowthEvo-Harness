# GrowthEvo Runtime Architecture

GrowthEvo separates causal estimation, semantic planning, numeric policy improvement, execution constraints, process credit, counterfactual evaluation, and evidence promotion into explicit contracts. The result is a modular runtime in which each layer has a clear statistical or operational responsibility.

## Architecture at a glance

| Layer | Responsibility | Primary components |
| --- | --- | --- |
| **Evidence input** | Preserve logged/randomized decisions, outcomes, identities, and propensities | treatment records, benchmark adapters, event store |
| **Causal estimation** | Estimate incremental treatment effects with held-out nuisance predictions | `CrossFittedDRLearner`, CATE backends |
| **Serving state** | Convert causal estimates into support-aware runtime beliefs | `CausalUpliftServingBridge`, `CausalBelief` |
| **Planning** | Form growth intent and information-acquisition hypotheses | `GrowthHypothesisPlanner` |
| **Policy** | Choose numeric channel/offer/timing/budget decisions | `HierarchicalGrowthPolicy`, `SupportAnchoredPolicyImprover` |
| **Execution control** | Enforce consent, budget, risk, fatigue, and frequency contracts | legal-action gate, tool registry |
| **Learning signal** | Record business outcomes and process-level trajectory credit | causal reward, GrowthPRM, GAE export |
| **Evaluation** | Estimate target-policy value and evidence strength | OPE panel, support diagnostics, conformal calibration |
| **Verification** | Apply evidence and constraint rules to candidate policies | `CounterfactualVerifier` |
| **Evolution** | Propose bounded improvements from verified failure traces | Harness evolution layer |

This separation keeps causal evidence, planner intent, policy optimization, execution safety, and promotion logic independently inspectable.

## 1. Causal learning path

`LoggedTreatmentRecord` stores the full behavior-policy propensity vector. For treatment `a` versus `NO_TREATMENT`, propensities are normalized within the treatment/control pair before AIPW pseudo-outcome construction.

`CrossFittedDRLearner` uses a held-out learning contract:

1. assign treatment/control rows to stratified folds, optionally respecting `group_id`;
2. fit treatment and control nuisance outcome models on the complementary folds;
3. generate doubly-robust pseudo-outcomes on held-out rows;
4. fit the second-stage effect learner on out-of-fold pseudo-outcomes;
5. record overlap and OOF residual diagnostics;
6. expose distributional-support information at serving time.

The reference Ridge implementation keeps the core dependency-light and auditable. Pluggable learners can provide tree-based, causal-forest, boosted, or neural estimation while preserving the same cross-fitting contract.

## 2. CATE serving

`CausalUpliftServingBridge` maps fitted treatment-effect models into `UserObservation` fields for channel-level effect, uncertainty, and support.

```text
channel_effects
channel_uncertainty
channel_support
```

`natural_conversion` remains separate from treatment uplift throughout the runtime. Distributional support contributes to serving confidence so policy optimization can distinguish strong in-distribution evidence from extrapolative estimates.

## 3. Causal belief state

`CausalBelief` is the decision-state representation used by downstream planning and policy layers.

```text
natural_conversion = P(Y=1 | no treatment, x)
channel_uplift[a]   = E[Y(a) - Y(no treatment) | x]
```

The belief can also carry LTV, uncertainty, fatigue, churn risk, spend, touch counts, lifecycle state, and consented channels.

## 4. Hierarchical decision contract

The semantic option layer represents lifecycle intent:

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

The numeric action layer resolves channel, creative, send time, offer value, expected direct budget, frequency cost, expected uplift, and uncertainty.

`NO_TREATMENT` is represented explicitly with zero treatment uplift, zero treatment budget, and zero touch cost. This gives the optimizer a native holdout action rather than treating non-intervention as an exception.

## 5. Support-anchored policy improvement

`SupportAnchoredPolicyImprover` combines discrete action value/cost estimates with the behavior-policy distribution.

For a candidate action `a`, the policy is represented as a bounded mixture with the behavior policy:

```math
\pi_a^{(\eta)}=(1-\eta)\mu+\eta\delta_a.
```

The feasible update mass is determined jointly by:

- action support;
- total-variation trust region;
- conservative expected-cost limits;
- pessimistic candidate value;
- optional externally calibrated lower/upper bounds.

Candidate selection is performed on the final feasible policies themselves. `NO_TREATMENT` remains available as the conservative action when treatment evidence or cost feasibility favors abstention.

## 6. Legal action gate

The legal-action gate runs before side effects. It enforces consent, total budget, offer caps, fatigue, churn risk, and frequency constraints such as 24-hour and 7-day touch limits.

The gate is a deterministic runtime contract. Policy learning optimizes within this legal action space rather than learning to reinterpret those constraints.

## 7. Cost accounting

`GrowthAction.budget` represents the expected direct economic cost of an action. Offer cost is incorporated into the policy-side budget contract so downstream simulation and accounting use one consistent cost definition.

## 8. Event sourcing

Important runtime decisions are recorded in a hash-chained event stream. Representative event classes include:

```text
GOAL_COMPILED
BELIEF_UPDATED
HYPOTHESIS_PLANNED
ACTION_PROPOSED
ACTION_ALLOWED
ACTION_BLOCKED
FEEDBACK_OBSERVED
REWARD_ASSIGNED
PROCESS_REWARD_ASSIGNED
ROLLOUT_EVALUATED
VERIFICATION_COMPLETED
FAILURE_CLASSIFIED
PATCH_PROPOSED
```

The in-memory implementation can be replaced by a durable database or event-log backend while retaining append-only ordering and event semantics.

## 9. GrowthPRM and planner training

`GrowthProcessRewardModel` scores planner/tool steps using potential change, evidence gain, action confidence, tool outcome, direct cost, duplicate evidence, and irreversible-side-effect signals.

`TrajectoryTrainerAdapter` exports backend-neutral Agent-RL records containing:

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

GAE supports `credit_boundary` resets for declared dynamics discontinuities such as rollback, environment reset, user/segment switch, or delayed-outcome attribution boundaries. Export-window truncation remains metadata and does not redefine the underlying dynamics.

## 10. Off-policy evaluation

The OPE layer evaluates candidate policies from logged cohorts and reports both estimates and evidence diagnostics.

Supported estimators include:

- Direct Method;
- IPS and SNIPS;
- Doubly Robust;
- SWITCH-DR;
- DR-OS;
- cross-fitted β*-IPS;
- Meta-OPE / BLUE-style candidates.

Diagnostics include estimator-specific standard error, ESS / ESS ratio, target-policy support coverage, maximum importance weight, mean-weight normalization, and weight coefficient of variation. Protocol-defined clusters can be used for cluster-robust uncertainty when the experiment supplies a defensible cluster identity.

## 11. Conformal calibration

`ConformalPolicyCalibrator` fits one-sided residual margins from calibration cohorts. Lower margins can be attached to value/ROI quantities and upper margins to cost or risk quantities.

The calibrated bounds are passed into policy improvement and verification through explicit fields, keeping prediction diagnostics separate from evidence bounds.

## 12. Counterfactual verification

`CounterfactualVerifier` consumes the policy estimate, uncertainty, support diagnostics, calibration results, and business-constraint aggregates. Its outcome space is:

```text
PASS
FAIL
INSUFFICIENT_EVIDENCE
```

This gives promotion logic a stable evidence contract shared across replay, benchmark, shadow, and production-oriented evaluation environments.

## 13. GrowthAgentBench

GrowthAgentBench is the built-in synthetic contextual-bandit oracle used for deterministic regression testing. It provides heterogeneous treatment effects, context-dependent behavior propensities, known potential outcomes, and held-out evaluation for CATE error and policy regret.

It complements the public-data evidence paths by giving CI an inspectable ground-truth environment for mathematical and runtime invariants.

## 14. Risk-sensitive planning

`RiskSensitiveMPC` evaluates candidate plans through multi-seed stochastic rollout. The state model can evolve fatigue, churn risk, spend, touch counts, intent, and effective treatment response under normal and stress scenarios.

Candidate ranking uses downside return and constraint risk:

```math
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation).
```

This provides a long-horizon risk layer for planning while causal promotion remains anchored to logged or experimental evidence.

## 15. Two-timescale learning

### Fast loop

The decision policy adapts channel, offer, timing, and treatment allocation from causal state and observed outcomes. The mainline contextual improvement kernel provides a stable deployment-facing contract for support-aware policy updates.

### Slow loop

Harness evolution analyzes verified failure traces and proposes bounded changes to planner, feature, memory, tool, delegation, exploration, and reward-shaping coordinates.

Core metric, consent, budget, event, verification, and no-treatment semantics remain stable across those proposals.

## 16. Extension points

GrowthEvo's architecture is designed to host specialized implementations behind stable interfaces:

| Contract | Example integrations |
| --- | --- |
| Event storage | Postgres, Kafka, durable event logs |
| Semantic planner | LLM or trained planning model |
| CATE backend | CausalML, EconML, causal forests, boosted or neural uplift |
| Sequential policy trainer | BC, IQL, CQL, Decision Transformer |
| World model | calibrated learned user simulator / digital twin |
| Execution tools | CRM, ads, messaging, MCP-compatible adapters |
| Planner post-training | PPO, GRPO, Agent-RL training systems |

The architecture keeps causal facts, consent, constraints, event history, and evidence promotion contracts owned by GrowthEvo while allowing the surrounding modeling ecosystem to evolve independently.
