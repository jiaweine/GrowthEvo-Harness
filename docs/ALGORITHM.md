# GrowthEvo Causal Decision Algorithm

## Objective

GrowthEvo optimizes **incremental long-horizon value** under user, evidence, and business constraints.

For user state `x` and treatment `a`, the primitive causal quantity is:

```math
\tau(x,a)=\mathbb{E}[Y(a)-Y(a_0)\mid X=x],
\qquad a_0=\mathrm{NO\_TREATMENT}.
```

The runtime can use a decomposed shaping reward for sequential learning:

```math
r_t=
 w_c\widehat\tau^{conv}_t
 +w_l\widehat\tau^{ltv}_t
 +w_r\Delta retention_t
 -\lambda_b cost_t
 -\lambda_f fatigue_t
 -\lambda_q risk_t
 -\lambda_u uncertainty_t.
```

Benchmark promotion is evaluated through the repository's locked evidence protocols, keeping training reward design and public evidence selection as separate contracts.

---

## 1. Hierarchical decision policy

The semantic option policy selects a lifecycle intent:

```math
z_t \sim \pi_H(z\mid b_t,g),
```

while the numeric policy selects the executable action:

```math
a_t \sim \pi_A(a\mid b_t,z_t).
```

This division lets semantic reasoning operate at the goal/hypothesis level while channel, offer, timing, and budget decisions remain inside a numeric policy contract.

## 2. Legal action space

Learning and planning operate over a legal action set:

```math
\mathcal{A}_{legal}(b_t)=
\mathcal{A}_{registered}
\cap\mathcal{A}_{consent}
\cap\mathcal{A}_{budget}
\cap\mathcal{A}_{frequency}
\cap\mathcal{A}_{risk}.
```

Consent, budget, frequency, and risk gates are applied before treatment side effects. `NO_TREATMENT` is represented directly in the action space.

---

## 3. Group-aware cross-fitted causal estimation

A logged treatment record stores the full behavior-policy propensity vector.

For treatment `a` versus control `a₀`, the pairwise propensity is:

```math
e_a(x)=\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
```

Nuisance models are fitted outside each evaluation fold. Held-out rows receive the DR pseudo-outcome:

```math
\widetilde\tau_i =
\widehat m_1(x_i)-\widehat m_0(x_i)
+\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
```

The second-stage effect learner is fitted on out-of-fold pseudo-outcomes. When `group_id` is provided, repeated units remain in the same fold assignment.

The learner contract additionally exposes:

- strict positivity semantics;
- practical overlap diagnostics;
- explicit propensity stabilization choices;
- OOF residual diagnostics;
- regularized Mahalanobis distributional support;
- pluggable nuisance and effect backends.

The bundled Ridge learner is the dependency-light reference backend; tree, forest, boosted, or neural learners can plug into the same cross-fitting contract.

---

## 4. CATE serving

`CausalUpliftServingBridge` converts fitted treatment-effect models into channel-level runtime fields:

```text
channel_effects
channel_uncertainty
channel_support
```

The serving layer preserves raw causal effects and exposes support information separately. The policy layer can therefore use both expected incremental value and the strength of the local data support.

---

## 5. Calibrated support-anchored policy improvement

Safe Policy Improvement evaluates candidate actions around the observed behavior policy.

With supplied lower and upper bounds:

```math
Q_a^- = L_a,
\qquad
C_a^+ = U_a.
```

A candidate direction toward action `a` is:

```math
\pi_a^{(\eta)}=(1-\eta)\mu+\eta\delta_a.
```

The feasible update mass is resolved from:

- action support;
- total-variation trust region;
- expected-cost constraint;
- pessimistic candidate value;
- optional calibrated/inferential bounds.

For the TV constraint:

```math
\eta
\le
\frac{\epsilon_{TV}}{1-\mu(a\mid x)}.
```

Candidate policies are ranked after these constraints are applied, so optimization happens directly in the final feasible policy space.

---

## 6. Off-policy evaluation

For logged action `a_i`, reward `r_i`, behavior propensity `\mu(a_i\mid x_i)`, and target policy `\pi(a_i\mid x_i)`:

```math
w_i=\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)}.
```

IPS is:

```math
\widehat V_{IPS}=\frac{1}{n}\sum_i w_i r_i.
```

Doubly Robust evaluation is:

```math
\widehat V_{DR}=\frac{1}{n}\sum_i
\left[
\widehat q_\pi(x_i)
+w_i(r_i-\widehat q(x_i,a_i))
\right].
```

GrowthEvo's flagship efficient estimator is cross-fitted β*-IPS. Let:

```math
Z_i=w_i-1.
```

Estimate β outside the current evaluation fold:

```math
\widehat\beta^*_{-f(i)}
=
\frac{\widehat{\mathrm{Cov}}_{-f(i)}(wR,Z)}
{\widehat{\mathrm{Var}}_{-f(i)}(Z)}.
```

Then:

```math
\widehat V_{\beta,CF}
=
\frac1n\sum_i
\left[w_i r_i-\widehat\beta^*_{-f(i)}(w_i-1)\right].
```

The full estimator panel contains DM, IPS, SNIPS, DR, SWITCH-DR, DR-OS, cross-fitted β*-IPS, and Meta-OPE candidates.

### Evidence diagnostics

Every OPE result can carry:

- standard error;
- ESS and ESS ratio;
- target-policy support coverage;
- maximum importance weight;
- mean-weight normalization diagnostics;
- importance-weight coefficient of variation;
- protocol-defined cluster-robust uncertainty.

```math
ESS=\frac{(\sum_i w_i)^2}{\sum_i w_i^2}.
```

These diagnostics participate in the predeclared evidence gate before benchmark estimator ranking.

---

## 7. One-sided conformal verification

For lower-bound calibration:

```math
r_i^{lower}=\widehat y_i-y_i.
```

For upper-bound calibration:

```math
r_i^{upper}=y_i-\widehat y_i.
```

The finite-sample quantile is:

```math
q_{1-\alpha}=r_{(\lceil(n+1)(1-\alpha)\rceil)}.
```

The resulting margins can be attached to value/ROI lower bounds and spend/fatigue/churn upper bounds. `CounterfactualVerifier` combines these quantities with statistical uncertainty and business constraints.

Verifier states are:

```text
PASS
FAIL
INSUFFICIENT_EVIDENCE
```

---

## 8. Long-horizon process credit

GrowthPRM uses potential-based shaping plus observation-grounded signals:

```math
r_t^{proc}=
\gamma\Phi(s_{t+1})-\Phi(s_t)
+\lambda_{obs}(1-H(a_t))\Delta Evidence_t
-Cost_t-Penalty_t.
```

The signal can incorporate evidence gain, action confidence, tool outcomes, duplicate evidence, direct economic cost, and irreversible-side-effect signals.

`TrajectoryTrainerAdapter` computes GAE:

```math
\delta_t=r_t+\gamma V(s_{t+1})-V(s_t),
```

```math
A_t=\delta_t+\gamma\lambda A_{t+1}.
```

`credit_boundary` resets propagation at declared dynamics discontinuities such as rollback, reset, user/segment switch, or delayed-outcome attribution boundaries.

---

## 9. Risk-sensitive model-based planning

The world-model layer evaluates multi-step candidates through stochastic rollout. State evolution can include fatigue, churn risk, spend, touch counts, intent, and effective treatment response.

Candidate returns are ranked by downside CVaR and constraint risk:

```math
CVaR_\alpha(R)=\mathbb E[R\mid R\le VaR_\alpha(R)],
```

```math
Score(plan)=CVaR_{\alpha}(Return)-\lambda P(ConstraintViolation).
```

Stress scenarios perturb uplift, cost, and fatigue dynamics to test plan sensitivity before downstream deployment stages.

---

## 10. Harness evolution

Harness evolution operates on a slower timescale than treatment-policy learning. Verified failure categories map to bounded proposal coordinates such as exploration, routing, process reward, feature construction, or planner behavior.

| Evidence pattern | Typical evolution direction |
| --- | --- |
| Low support / ESS | collect additional evidence or increase bounded exploration |
| Counterfactual value regression | reduce proxy-driven credit and strengthen causal evidence use |
| Budget / ROI pressure | favor lower-cost routing and stronger cost preview |
| Fatigue pressure | favor holdout or lower-touch retention strategies |

The evolution layer proposes changes while core metric, legal-action, event, and verification contracts remain stable.

---

## 11. Evidence-governed benchmark selection

Real-world benchmark selection follows a fixed staged contract:

| Stage | Action |
| ---: | --- |
| **1** | Freeze experiment plan, source, split, candidate configuration, and evidence gates |
| **2** | Materialize the realized data/model manifest |
| **3** | Open validation and score every predeclared candidate |
| **4** | Apply evidence eligibility and select one winner |
| **5** | Freeze the winner |
| **6** | Evaluate that winner on the independent final holdout |
| **7** | Persist plan, manifest, evidence, environment, and code fingerprints |

Current accepted full-data artifacts cover:

- **Criteo Uplift v2.1** targeting: S-Learner validation winner, **+0.93791 pp** population incremental visit and **+9.37910 pp** selected top-10% incremental visit;
- **Open Bandit Dataset** OPE: IPS validation winner, final support **1.0000** and ESS ratio **0.16123**.

See `docs/REAL_WORLD_BENCHMARKS.md` for the complete benchmark protocol.

---

## 12. GrowthAgentBench

The repository includes a reproducible synthetic contextual-bandit oracle with:

- heterogeneous treatment effects;
- context-dependent behavior propensities;
- explicit `NO_TREATMENT` potential outcomes;
- configurable outcome noise;
- held-out CATE RMSE / MAE / bias;
- support / uncertainty diagnostics;
- oracle policy value and regret;
- safety and trajectory-credit invariants.

GrowthAgentBench gives CI an inspectable ground-truth environment, while Criteo and Open Bandit supply the public locked real-world evidence layer.

## Implementation map

| Algorithm component | Source |
| --- | --- |
| Cross-fitted DR CATE | `growthevo/causal/dr_learner.py` |
| CATE serving | `growthevo/causal/serving.py` |
| Safe Policy Improvement | `growthevo/rl/safe_policy_improvement.py` |
| OPE estimator panel | `growthevo/rl/ope.py` |
| Conformal calibration | `growthevo/rl/conformal.py` |
| Risk-sensitive planning | `growthevo/rl/model_based.py` |
| Process reward | `growthevo/rl/process_reward.py` |
| Dynamics-aware trajectory credit | `growthevo/training/trajectory.py` |
| Locked OPE | `growthevo/bench/locked_ope_cli.py` |
| Locked targeting | `growthevo/bench/locked_targeting_cli.py` |
