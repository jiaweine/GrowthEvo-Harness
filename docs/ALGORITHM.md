# CausalLift-HRL

## Objective

GrowthEvo optimizes incremental long-horizon value under hard user and business constraints.

For user state `x` and treatment `a`, the primitive causal quantity is:

\[
\tau(x,a)=\mathbb{E}[Y(a)-Y(a_0)\mid X=x]
\]

where `a0` is `NO_TREATMENT`.

The Runtime reward is a decomposed shaping signal:

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

The frozen North-Star metric and policy-promotion evidence are evaluated separately from this short-horizon shaping reward.

## 1. Hierarchical policy

The semantic option policy selects:

\[
z_t \sim \pi_H(z\mid b_t,g)
\]

and the numeric action policy selects:

\[
a_t \sim \pi_A(a\mid b_t,z_t).
\]

The split allows an LLM planner to reason about lifecycle intent without giving it unrestricted control over budget, incentive magnitude or channels.

## 2. Legal action space

Learning is conditioned on a legal action set:

\[
\mathcal{A}_{legal}(b_t)=
\mathcal{A}_{registered}
\cap\mathcal{A}_{consent}
\cap\mathcal{A}_{budget}
\cap\mathcal{A}_{frequency}
\cap\mathcal{A}_{risk}.
\]

Illegal actions are rejected before side effects and cannot earn a training reward for bypassing a hard constraint.

## 3. Cross-fitted causal bootstrap

A logged decision stores the full behavior-policy propensity vector, not only the propensity of the observed action.

For treatment `a` versus control `a0`, multi-action propensities are renormalized inside the pair:

\[
e_a(x)=\frac{\mu(a|x)}{\mu(a|x)+\mu(a_0|x)}.
\]

Nuisance outcome models are trained on K-1 folds. For each held-out record, the DR pseudo-outcome is:

\[
\tilde\tau_i =
\hat m_1(x_i)-\hat m_0(x_i)
+\frac{A_i(Y_i-\hat m_1(x_i))}{\hat e(x_i)}
-\frac{(1-A_i)(Y_i-\hat m_0(x_i))}{1-\hat e(x_i)}.
\]

The second-stage effect model is trained only on out-of-fold pseudo-outcomes. This gives the Runtime a causal uplift estimate while reducing direct nuisance-model leakage.

The reference backend is dependency-free ridge regression. Production backends can replace it with causal forests, DR-Learner implementations, CausalML, EconML or neural uplift models without changing the serving contract.

## 4. CATE serving

`CausalUpliftServingBridge` converts fitted treatment-effect models into:

```text
channel_effects
channel_uncertainty
channel_support
```

Low support inflates uncertainty instead of silently becoming a confident zero effect. This makes abstention a first-class serving behavior.

The serving uncertainty is a model diagnostic, not a replacement for cohort-level OPE or randomized evidence.

## 5. Support-anchored conservative policy improvement

For each discrete action, construct a pessimistic value:

\[
LCB(a)=\hat Q(a)-z\hat\sigma(a).
\]

Unsupported actions are excluded from improvement. `NO_TREATMENT` remains available as a safe fallback.

Let `a*` be the best supported pessimistic action. The candidate policy is a bounded interpolation with the logging policy:

\[
\pi_{new}=(1-\eta)\mu+\eta\delta_{a^*}.
\]

`η` is limited by:

- a total-variation update cap;
- an expected-cost upper bound;
- the requirement that pessimistic candidate value exceed pessimistic behavior value.

This kernel prevents a value model from making an immediate OOD jump. It does not replace formal deployment verification.

## 6. Off-policy evaluation

For logged action `a_i`, reward `r_i`, behavior propensity `\mu(a_i|x_i)` and target policy `\pi(a_i|x_i)`:

\[
\hat V_{IPS}=\frac{1}{n}\sum_i\frac{\pi(a_i|x_i)}{\mu(a_i|x_i)}r_i.
\]

The DR estimator is:

\[
\hat V_{DR}=\frac{1}{n}\sum_i
\left[
\hat V(x_i,\pi)+
\frac{\pi(a_i|x_i)}{\mu(a_i|x_i)}
(r_i-\hat Q(x_i,a_i))
\right].
\]

GrowthEvo also implements an estimated additive-control-variate estimator:

\[
\hat V_{\beta}=\frac1n\sum_i[w_i r_i-\hat\beta(w_i-1)].
\]

Every estimate is accompanied by support diagnostics:

- effective sample size and ESS ratio;
- practical logging support coverage;
- maximum importance weight;
- weight coefficient of variation.

A large nominal cohort with poor overlap is treated as weak evidence.

## 7. Calibrated promotion gate

Candidate policies are promoted only if:

\[
LCB(V(\pi_c)-V(\pi_b))>\delta
\]

and all configured constraints pass.

When conformal calibration margins are supplied, value and ROI use lower bounds while spend, fatigue and churn use upper bounds. The Verifier takes the more conservative of statistical and calibrated value bounds.

The gate has three outcomes:

```text
PASS
FAIL
INSUFFICIENT_EVIDENCE
```

Lack of support is not mislabeled as evidence that the policy is worse.

## 8. Long-horizon process credit

GrowthPRM uses potential-based progress plus observation-grounded credit:

\[
r_t^{proc}=
\gamma\Phi(s_{t+1})-\Phi(s_t)
+\lambda_{obs}(1-H(a_t))\Delta Evidence_t
-Cost_t-Penalty_t.
\]

The signal rewards real evidence/progress and penalizes failed tools, duplicate evidence, cost and irreversible side effects.

For planner post-training, `TrajectoryTrainerAdapter` computes GAE:

\[
\delta_t=r_t+\gamma V(s_{t+1})-V(s_t),
\]

\[
A_t=\delta_t+\gamma\lambda A_{t+1}.
\]

`credit_boundary` resets propagation across rollback, reset, segment switch or delayed-outcome attribution boundaries. This prevents unrelated transition regimes from sharing local credit.

## 9. Risk-sensitive model-based planning

The World Model is used for stress testing and candidate ranking, not as causal ground truth.

For each candidate plan, multi-seed rollout returns are scored with lower-tail CVaR and constraint violation probability:

\[
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation).
\]

Stress scenarios can reduce uplift, increase cost and amplify fatigue before a candidate reaches shadow traffic.

## 10. Harness evolution

Failure-driven evolution operates on a slower timescale than policy learning.

Examples:

```text
insufficient support / ESS
  -> increase bounded exploration or collect holdout evidence

counterfactual value regression
  -> reduce raw-conversion proxy credit

budget / ROI failures
  -> prefer lower-cost routing and stronger cost preview

fatigue failures
  -> prefer holdout / retention hypotheses
```

Each proposal modifies one whitelisted coordinate. The Evolver cannot rewrite the North-Star metric, legal-action gate or Verifier.

## 11. GrowthAgentBench

The repository includes a reproducible synthetic contextual-bandit oracle with:

- heterogeneous treatment effects;
- context-dependent behavior propensities;
- explicit `NO_TREATMENT` potential outcome;
- configurable outcome noise;
- held-out CATE RMSE / MAE / bias;
- support / uncertainty diagnostics;
- oracle policy regret.

Synthetic benchmark metrics are implementation regression tests, not product lift.

Public-dataset evaluation should add Open Bandit Dataset / Criteo adapters and preserve logging propensities, legal action state, delayed outcomes and holdout semantics.

## 12. Claims boundary

The repository does not describe neural IQL/CQL/CPO/GRPO, learned user simulators or real online uplift as completed until the corresponding training code and reproducible evaluation exist.

The required sequence is:

```text
code
  -> reproducible benchmark
  -> OPE / uncertainty diagnostics
  -> shadow / canary
  -> verified result
  -> README claim
```
