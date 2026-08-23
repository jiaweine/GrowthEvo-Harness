# CausalLift-HRL

## Objective

GrowthEvo optimizes incremental long-horizon value under hard user and business constraints.

For user state `x` and treatment `a`, the primitive causal quantity is:

\[
\tau(x,a)=\mathbb{E}[Y(a)-Y(a_0)\mid X=x]
\]

where `a0` is `NO_TREATMENT`.

The runtime outcome reward is a decomposed proxy for the constrained objective:

\[
r_t=
 w_c\hat\tau^{conv}_t
 +w_l\hat\tau^{ltv}_t
 +w_r\Delta retention_t
 -\lambda_b cost_t
 -\lambda_f fatigue_t
 -\lambda_q risk_t
 -\lambda_u uncertainty_t.
\]

The frozen North-Star metric is evaluated separately from short-horizon reward shaping.

## Hierarchical policy

The semantic option policy selects:

\[
z_t \sim \pi_H(z\mid b_t,g)
\]

and the numeric action policy selects:

\[
a_t \sim \pi_A(a\mid b_t,z_t).
\]

This split lets an LLM planner reason about lifecycle intent without giving it unrestricted control over budget, incentive magnitude or channels.

## Legal action space

Learning is conditioned on a legal action set:

\[
\mathcal{A}_{legal}(b_t)=
\mathcal{A}_{registered}
\cap\mathcal{A}_{consent}
\cap\mathcal{A}_{budget}
\cap\mathcal{A}_{frequency}
\cap\mathcal{A}_{risk}.
\]

A policy cannot receive positive training credit for bypassing a hard constraint because illegal actions are rejected before side effects.

## Logged-data contract

At minimum, offline training/evaluation needs:

- context / belief features;
- selected action;
- behavior propensity;
- policy identifier;
- direct cost;
- delayed outcome timestamps;
- holdout assignment;
- consent / budget / frequency state.

Without behavior propensities or randomized evidence, OPE claims must be explicitly limited.

## Causal bootstrap

Treatment-effect models should estimate conversion, retention and LTV incrementality. Cross-fitting is preferred for evaluation to reduce overfit bias.

Outputs become belief features:

```text
uplift_mean[channel]
uplift_uncertainty[channel]
baseline_outcome
```

The current repository keeps these values as typed inputs so CausalML, EconML or custom models can be integrated later without changing runtime semantics.

## Offline policy optimization

Candidate learned policies should be conservative against logged behavior.

- Contextual bandits are appropriate for genuinely one-step decisions.
- IQL/CQL-style methods become relevant when the data represents sequential interventions and delayed state transitions.
- Constraint handling should remain explicit rather than hidden entirely inside reward penalties.

A complex RL algorithm should not be used simply because the product is called an Agent.

## Constrained objective

A generic constrained policy objective is:

\[
\max_\pi J(\pi)-\sum_j\lambda_j(C_j(\pi)-c_j).
\]

Examples of constraints include:

- minimum ROI;
- maximum budget;
- maximum fatigue;
- maximum churn risk;
- consent and frequency limits.

The deployment verifier remains independent from learned Lagrange multipliers.

## GrowthPRM process reward

Long-horizon business outcomes are sparse, so the planner also receives step-level shaping:

\[
r_t^{process}
=
\gamma\Phi(s_{t+1})-\Phi(s_t)
+\lambda_{obs}(1-H(a_t))\Delta Evidence_t
-Cost_t-Penalty_t.
\]

The potential is:

\[
\Phi(s)=
w_g GoalProgress(s)
+w_e EvidenceQuality(s)
+w_c ConstraintSlack(s).
\]

The observation term rewards an environment/tool response when it materially improves evidence and the preceding action was relatively confident. This keeps process credit grounded in interaction outcomes instead of verbose reasoning text.

Explicit negative terms cover:

- tool failure;
- duplicate evidence;
- direct tool/action cost;
- irreversible side effects.

Trajectory output separates `process_total` from `terminal_outcome`. The final promotion decision still uses cohort-level causal evidence rather than process reward alone.

## Off-policy evaluation

For logged action `a_i`, reward `r_i`, behavior propensity `\mu(a_i|x_i)` and target probability `\pi(a_i|x_i)`:

\[
w_i=\frac{\pi(a_i|x_i)}{\mu(a_i|x_i)}.
\]

### IPS

\[
\hat V_{IPS}=\frac{1}{n}\sum_i w_i r_i.
\]

### Doubly Robust

\[
\hat V_{DR}=\frac{1}{n}\sum_i
\left[
\hat V(x_i,\pi)+w_i(r_i-\hat Q(x_i,a_i))
\right].
\]

### β*-IPS additive control variate

GrowthEvo also implements an estimated additive control variate:

\[
\hat V_{\beta}=\frac1n\sum_i\left[w_i r_i-\hat\beta(w_i-1)\right]
\]

with

\[
\hat\beta=
\frac{\widehat{Cov}(wr,w-1)}{\widehat{Var}(w-1)}.
\]

This estimator is useful only when the logged data and support assumptions are appropriate. It does not repair hidden confounding or missing support.

### Overlap diagnostics

Every OPE result also tracks:

- effective sample size;
- ESS / nominal sample ratio;
- practical support coverage;
- maximum importance weight;
- importance-weight coefficient of variation.

A high point estimate with poor support is treated as weak evidence, not as a deployable win.

## Split-conformal calibration

For matured historical cohorts, fit one-sided residual margins.

For value delta:

\[
e_i=\widehat{\Delta V}_i-\Delta V_i,
\qquad
q=q_{1-\alpha}(e_1,\dots,e_n)
\]

and for a new prediction:

\[
LCB_{conf}(\Delta V)=\widehat{\Delta V}-q.
\]

The same pattern is used for ROI lower bounds and spend/fatigue/churn upper bounds with the appropriate residual direction.

Implementation detail: `ConformalMargins` stores **residual margins**, not absolute bounds. Field names therefore use the suffix `_margin`, and methods such as `value_lcb()` / `spend_ucb()` apply the margin to a new prediction.

Conformal calibration is used only when calibration/test exchangeability is plausible. Distribution shift should trigger recalibration or abstention.

## Counterfactual promotion gate

A candidate must first have enough usable evidence:

```text
sample size >= threshold
ESS >= threshold
ESS ratio >= threshold
support coverage >= threshold
max importance weight <= threshold
```

Otherwise the result is:

```text
INSUFFICIENT_EVIDENCE
```

With sufficient evidence, promotion requires:

\[
LCB(V(\pi_c)-V(\pi_b))>\delta
\]

where the final LCB is the more conservative of the asymptotic and conformal value bounds when calibration is available.

ROI, budget, fatigue and churn constraints are checked using their conservative lower/upper bounds.

The gate has exactly three outcomes:

```text
PASS
FAIL
INSUFFICIENT_EVIDENCE
```

This tri-state contract is important for safe experimentation because “not enough support” is not equivalent to “candidate is worse.”

## Risk-sensitive model-based planning

Growth interventions are sequential: one touch changes fatigue, churn, spend and future uplift.

`RiskSensitiveMPC` evaluates candidate plans with multi-seed stochastic rollouts under nominal and stressed world-model parameters.

For return samples `R_1, ..., R_K`, use lower-tail CVaR:

\[
CVaR_{\alpha}(R)=
\frac{1}{|\mathcal I_{tail}|}
\sum_{k\in\mathcal I_{tail}}R_k.
\]

Candidate score:

\[
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation).
\]

This layer is intentionally a stress-test/ranking mechanism. It cannot promote a policy without logged or experimental causal evidence.

## Planner post-training

If an LLM planner is trained with Agent-RL, the training data should come from real Harness trajectories with process signals such as:

- correct information/tool selection;
- reduction in uncertainty;
- feasible experiment proposals;
- good stop/holdout decisions;
- low unnecessary tool cost;
- recovery quality after tool or evidence failure.

GrowthPRM may provide step credit, while the numeric policy remains a separate serving component. Planner training must never redefine the North-Star metric or frozen deployment constraints.

## Harness evolution

Failure-driven evolution operates more slowly than policy learning.

Examples:

```text
insufficient ESS / support
  -> increase bounded exploration or collect targeted holdout evidence

counterfactual value regression
  -> reduce misleading short-term proxy credit

budget / ROI failures
  -> prefer lower-cost routing and pre-action ROI preview

fatigue failures
  -> prefer holdout or less invasive retention hypotheses

duplicate / useless tool evidence
  -> repair tool routing or query strategy
```

Each proposal modifies one whitelisted coordinate. Candidate patches must pass replay/stress and later shadow evaluation before becoming active configuration.

## Benchmark design

`GrowthAgentBench` should distinguish at least:

1. causal attribution;
2. delayed reward;
3. business constraints;
4. fatigue / user-cost constraints;
5. logging-policy support mismatch;
6. agentic information acquisition;
7. tool failures and recovery;
8. long-horizon distribution shift.

Recommended ablations:

```text
Rule workflow
ReAct planner
Contextual bandit
Uplift policy
Offline RL
Planner-RL without counterfactual verifier
CausalLift-HRL
+ overlap-aware OPE
+ calibrated promotion gate
+ GrowthPRM
+ risk-sensitive stress planning
+ Harness Evolution
```

Performance numbers should only be published after behavior-policy logging, datasets, training configuration and evaluation protocol are reproducible.
