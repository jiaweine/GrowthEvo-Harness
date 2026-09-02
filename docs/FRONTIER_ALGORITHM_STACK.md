# GrowthEvo Frontier Algorithm Stack

This document defines the canonical algorithm choices used by GrowthEvo-Harness. Components are selected by statistical fit, leakage resistance, evidence efficiency, deployment compatibility, and reproducibility under the repository's test and benchmark contracts.

## Canonical stack

| Layer | Canonical implementation | Design rationale |
| --- | --- | --- |
| **CATE** | Group-aware cross-fitted Doubly Robust learner | orthogonal held-out estimation, pluggable learners, explicit propensity semantics, OOF diagnostics, distributional support |
| **CATE serving** | Support-aware uplift serving bridge | preserves raw treatment effects while exposing uncertainty and support to runtime policy layers |
| **Safe PI** | Calibrated support-anchored final-feasible search | combines explicit bounds, support, TV trust regions, cost constraints, and direct ranking of deployable policies |
| **OPE** | Cross-fitted β*-IPS flagship plus estimator panel | efficient additive-control-variate estimator backed by DR/IPS/SNIPS/SWITCH-DR/DR-OS robustness candidates |
| **OPE uncertainty** | Estimator-specific IID or protocol-defined cluster-robust SE | aligns uncertainty with the experiment's repeated-unit structure |
| **OPE combination** | Meta-OPE / BLUE-style candidate | enables correlated-estimator combination under the same validation-governed benchmark contract |
| **Verification** | One-sided conformal calibration + counterfactual verifier | attaches explicit lower/upper margins to value, cost, and risk quantities |
| **Long horizon** | Stochastic rollout + downside CVaR | ranks plans by lower-tail return and constraint-violation probability |
| **Trajectory credit** | Dynamics-aware GAE | resets recursive credit only at declared dynamics discontinuities |
| **Sequential offline RL** | Backend-neutral KuaiRand export contract | supports specialized BC/IQL/CQL/Decision-Transformer trainers without coupling them to runtime evidence semantics |

## Selection principles

GrowthEvo's component choices follow six repository-wide principles:

1. **Orthogonality and held-out estimation** for causal nuisance and effect learning.
2. **Support-aware optimization** so policy updates remain grounded in logged evidence.
3. **Explicit uncertainty contracts** so diagnostics, calibrated bounds, and inferential quantities remain distinguishable.
4. **Final-feasible ranking** so optimization compares policies after deployment constraints are applied.
5. **Validation-governed empirical selection** for benchmark-specific estimator/model choices.
6. **Locked evidence promotion** so headline results remain tied to predeclared protocol and independent final holdout.

---

## 1. CATE · Group-aware cross-fitted DR

`growthevo/causal/dr_learner.py` implements a one-vs-control Doubly Robust treatment-effect contract with group-aware cross-fitting.

For treatment `a` and `NO_TREATMENT` control `a₀`, the pairwise propensity is:

```math
e_a(x)
=
\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
```

Held-out pseudo-outcomes use the standard DR/AIPW form:

```math
\widetilde\tau_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-
\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
```

The canonical contract includes:

- optional `group_id` fold assignment for repeated users/units;
- balanced group-aware folds;
- pluggable treatment/control nuisance learners;
- pluggable second-stage effect learners;
- explicit strict positivity and practical-overlap diagnostics;
- explicit propensity stabilization choices;
- out-of-fold second-stage residual diagnostics;
- regularized Mahalanobis distributional support.

The bundled Ridge learner is the dependency-light reference implementation. Specialized CATE backends can be injected without changing the cross-fitting or serving contracts.

### Distributional support

Serving-time support uses a regularized Mahalanobis distance:

```math
d_M(x)
=
\sqrt{(x-\bar x)^\top(\Sigma+\lambda I)^{-1}(x-\bar x)}.
```

With training support radius `r_q`, an extrapolation factor can be written as:

```math
\xi(x)=\max\left(0,\frac{d_M(x)}{r_q}-1\right),
```

and combined with overlap coverage to form a support score. This gives policy layers a continuous signal for training-manifold proximity rather than relying on feature-wise min/max checks.

---

## 2. Safe Policy Improvement · calibrated final-feasible search

`growthevo/rl/safe_policy_improvement.py` evaluates constrained candidate policies around the behavior policy.

In calibrated-bound mode:

```math
Q_a^- = L_a,
\qquad
C_a^+ = U_a.
```

A point-mass direction toward action `a` is represented as:

```math
\pi_a^{(\eta)}=(1-\eta)\mu+\eta\delta_a.
```

The feasible update mass is determined by action support, total-variation trust region, conservative expected cost, and minimum pessimistic improvement.

For the TV constraint:

```math
\eta
\le
\frac{\epsilon_{TV}}{1-\mu(a\mid x)}.
```

The final selector compares each constrained candidate after its feasible update mass is resolved. This aligns optimization directly with the policy that can actually be executed.

`NO_TREATMENT` remains a native action and participates in the same feasibility logic.

---

## 3. OPE · cross-fitted β*-IPS and robustness panel

The primary efficient estimator in `growthevo/rl/ope.py` is cross-fitted β*-IPS.

For importance weight

```math
w_i=\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)},
```

define

```math
Z_i=w_i-1.
```

The β coefficient for an evaluation row is estimated using data outside that row's evaluation fold:

```math
\widehat\beta^*_{-f(i)}
=
\frac{\widehat{\mathrm{Cov}}_{-f(i)}(wR,Z)}
{\widehat{\mathrm{Var}}_{-f(i)}(Z)}.
```

The cross-fitted estimate is:

```math
\widehat V_{\beta,CF}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[w_i r_i-\widehat\beta^*_{-f(i)}(w_i-1)\right].
```

The same evaluation surface also provides:

- Direct Method;
- IPS;
- SNIPS;
- Doubly Robust;
- SWITCH-DR;
- DR-OS;
- cross-fitted β*-IPS;
- Meta-OPE / BLUE-style candidates;
- same-sample β*-IPS diagnostic fields for reproduction analysis.

### Evidence diagnostics

Each policy evaluation can report:

- estimator-specific standard error;
- ESS and ESS ratio;
- target-policy-mass support coverage;
- maximum importance weight;
- mean importance weight and normalization error;
- importance-weight coefficient of variation;
- protocol-defined cluster-robust uncertainty.

```math
ESS=\frac{(\sum_i w_i)^2}{\sum_i w_i^2}.
```

These diagnostics are first-class inputs to the locked evidence gate.

### Benchmark-specific estimator selection

The library-level canonical estimator and the benchmark-specific validation winner serve different roles. A benchmark may predeclare several credible estimators and choose the one that best satisfies its validation objective.

The current full Open Bandit Dataset locked benchmark illustrates this contract: IPS won its frozen validation cohort and was therefore the estimator evaluated on final holdout. The estimator library still retains cross-fitted β*-IPS as its flagship efficient OPE implementation.

---

## 4. Conformal verification

`growthevo/rl/conformal.py` supports one-sided residual calibration.

Lower-bound residual:

```math
r_i^{lower}=\widehat y_i-y_i.
```

Upper-bound residual:

```math
r_i^{upper}=y_i-\widehat y_i.
```

The finite-sample order-statistic quantile is:

```math
q_{1-\alpha}=r_{(\lceil(n+1)(1-\alpha)\rceil)}.
```

The resulting margins can be attached to value, ROI, spend, fatigue, churn, or other quantities through explicit runtime fields. Multiple constraints can use family-wise correction when required by the verification protocol.

---

## 5. Long-horizon planning · downside CVaR

`growthevo/rl/model_based.py` evaluates candidate sequences through stochastic rollout with stateful fatigue, churn, spend, touch-count, intent, and treatment-response dynamics.

Downside CVaR is:

```math
CVaR_\alpha(R)=\mathbb E[R\mid R\le VaR_\alpha(R)].
```

Candidate plans are ranked with a risk-sensitive objective:

```math
Score(\pi)
=
CVaR_\alpha(R_\pi)
-\lambda\Pr(\mathrm{constraint\ violation}\mid\pi).
```

This provides a consistent long-horizon ranking surface for normal and stress scenarios.

---

## 6. Trajectory credit · dynamics-aware GAE

Potential shaping uses:

```math
F_t=\gamma\Phi(s_{t+1})-\Phi(s_t).
```

GAE uses:

```math
\delta_t=r_t+\gamma V(s_{t+1})-V(s_t),
```

```math
A_t=\delta_t+\gamma\lambda A_{t+1}.
```

`credit_boundary` marks declared dynamics discontinuities such as rollback, reset, user/segment switch, or delayed-outcome attribution boundaries. Ordinary export windows remain truncation metadata, preserving the underlying learning target across data batching choices.

---

## 7. Sequential offline-RL interface

KuaiRand adapters expose backend-neutral sequential training data. This keeps dataset and trajectory semantics stable while allowing research-specific trainers to vary.

Candidate backends include:

- Behavior Cloning;
- IQL;
- CQL;
- Decision Transformer;
- other sequence or value-based offline-RL systems.

The common contract preserves chronological state construction, action identity, reward timing, next-state semantics, truncation metadata, and planner credit boundaries.

---

## 8. Evidence-governed evolution

Algorithm evolution is evaluated at two levels:

### Implementation level

- mathematical invariants;
- deterministic regression tests;
- support and constraint behavior;
- Python/package compatibility;
- runtime and training demos.

### Empirical level

- predeclared candidate configuration;
- validation-only comparison;
- evidence eligibility gates;
- frozen winner;
- independent final holdout;
- persisted provenance and fingerprints.

This lets GrowthEvo incorporate new methods without coupling repository progress to novelty alone. New components enter the canonical stack when they improve the relevant statistical or operational contract and survive the corresponding evidence path.

## Current research directions

The stack aligns with research directions in:

- additive control variates and β*-IPS for efficient OPE;
- correlated-estimator combination / Meta-OPE;
- support-restricted safe policy improvement;
- orthogonal heterogeneous-treatment estimation with cross-fitting;
- calibrated one-sided verification;
- downside-CVaR model-based planning;
- dynamics-aware long-horizon credit assignment;
- backend-neutral agent and offline-RL training interfaces.

Exact benchmark outcomes remain recorded in the repository's locked evidence artifacts and `docs/REAL_WORLD_BENCHMARKS.md`.
