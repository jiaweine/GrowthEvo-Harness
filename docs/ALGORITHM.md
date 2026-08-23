# CausalLift-HRL

## Objective

GrowthEvo optimizes incremental long-horizon value under hard user and business constraints.

For user state `x` and treatment `a`, the primitive causal quantity is:

\[
\tau(x,a)=\mathbb{E}[Y(a)-Y(a_0)\mid X=x]
\]

where `a0` is `NO_TREATMENT`.

The runtime reward is a decomposed proxy for the constrained objective:

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

The frozen North-Star metric should be evaluated separately from short-horizon reward shaping.

## Hierarchical policy

The semantic option policy selects:

\[
z_t \sim \pi_H(z\mid b_t,g)
\]

and the numeric action policy selects:

\[
a_t \sim \pi_A(a\mid b_t,z_t).
\]

This split enables an LLM planner to reason about lifecycle intent without giving it unrestricted control over budget, incentive magnitude or channels.

## Legal action space

Learning is always conditioned on a legal action set:

\[
\mathcal{A}_{legal}(b_t)=
\mathcal{A}_{registered}
\cap\mathcal{A}_{consent}
\cap\mathcal{A}_{budget}
\cap\mathcal{A}_{frequency}
\cap\mathcal{A}_{risk}.
\]

A policy cannot receive a training reward for successfully bypassing a hard constraint because illegal actions are rejected before side effects.

## Offline-first training plan

### Stage 0 — logged-data contract

Store, at minimum:

- context / belief features
- action
- behavior propensity
- policy version
- direct cost
- delayed outcomes
- holdout assignment
- consent / budget / frequency state

Without propensity or randomized evidence, OPE claims should be explicitly limited.

### Stage 1 — causal bootstrap

Train treatment-effect models for conversion, retention and LTV. Cross-fitting is preferred for evaluation to reduce overfit bias.

Outputs become belief features:

```text
uplift_mean[channel]
uplift_uncertainty[channel]
baseline_outcome
```

### Stage 2 — offline policy optimization

Train conservative policies against logged behavior. Candidate algorithms include IQL and CQL when sequential data is available; contextual bandits are a better default when the decision is genuinely one-step.

A complex RL algorithm should not be used simply because the product is called an Agent.

### Stage 3 — constrained optimization

Represent ROI, budget and user-cost requirements as explicit constraints rather than large negative reward constants whenever possible.

Example Lagrangian form:

\[
\max_\pi J(\pi)-\sum_j\lambda_j(C_j(\pi)-c_j).
\]

The deployment gate remains independent from learned Lagrange multipliers.

### Stage 4 — planner post-training

If an LLM planner is introduced, train it on plan/tool/delegation trajectories while the numeric growth policy remains a separate serving component.

Planner reward should focus on:

- selecting the right information/tool
- reducing uncertainty
- proposing feasible experiments
- respecting stop/holdout decisions
- minimizing unnecessary tool cost

Do not let planner post-training redefine the North-Star metric.

## Delayed credit

For long-horizon outcomes, use a process reward only as a shaping signal. A generic decomposition is:

\[
r_t^{process}=\alpha A_t^{DR}+\beta(V_c(b_{t+1})-V_c(b_t))+\eta IG_t-\lambda C_t.
\]

Where:

- `A_DR` is an incremental doubly-robust advantage estimate,
- `V_c` is progress toward a causal long-horizon objective,
- `IG` is information gain from controlled exploration,
- `C` contains business and user costs.

The final promotion decision should still use cohort-level causal evidence.

## Off-policy evaluation

The repository currently implements reference IPS and Doubly Robust estimators.

For logged action `a_i`, reward `r_i`, behavior propensity `\mu(a_i|x_i)` and target policy `\pi(a_i|x_i)`:

\[
\hat V_{IPS}=\frac{1}{n}\sum_i\frac{\pi(a_i|x_i)}{\mu(a_i|x_i)}r_i.
\]

A DR estimator combines a value model with the importance-weighted residual:

\[
\hat V_{DR}=\frac{1}{n}\sum_i
\left[
\hat V(x_i,\pi)+
\frac{\pi(a_i|x_i)}{\mu(a_i|x_i)}
(r_i-\hat Q(x_i,a_i))
\right].
\]

Effective sample size is tracked because a large nominal cohort with extreme importance weights can still provide weak evidence.

## Promotion gate

Candidate policies are promoted only if:

\[
LCB(V(\pi_c)-V(\pi_b))>\delta
\]

and all configured constraints pass.

Current reference constraints include ROI, total spend, fatigue and churn risk.

The gate has three outcomes:

```text
PASS
FAIL
INSUFFICIENT_EVIDENCE
```

This tri-state contract is required for safe sequential experimentation.

## Harness evolution

Failure-driven evolution is slower than policy learning.

Examples:

```text
insufficient ESS
  -> increase bounded exploration coefficient

counterfactual value regression
  -> reduce raw-conversion proxy credit

budget / ROI failures
  -> prefer low-cost routing + ROI preview

fatigue failures
  -> prefer holdout / retention hypotheses
```

Each proposal modifies one whitelisted coordinate. Candidate patches must later be evaluated through replay and shadow cohorts before becoming active runtime configuration.

## Benchmark design

A future `GrowthAgentBench` should distinguish five sources of difficulty:

1. causal attribution,
2. delayed reward,
3. business constraints,
4. user-cost / fatigue constraints,
5. agentic information acquisition and tool failures.

Recommended ablations:

```text
Rule workflow
ReAct planner
Contextual bandit
Uplift policy
Offline RL
Planner-RL without counterfactual verifier
CausalLift-HRL
CausalLift-HRL + Harness Evolution
```

The repository should only publish performance numbers after the benchmark, behavior-policy logging and evaluation protocol are reproducible.
