# GrowthEvo Frontier Algorithm Stack

This file is the version-selection rule for the repository. GrowthEvo does **not** treat a branch, commit count, or newer-looking implementation as the canonical algorithm. The canonical stack is selected component by component using four criteria:

1. statistical correctness and leakage resistance;
2. algorithmic novelty / relevance to the current research frontier;
3. expected efficiency or performance under the assumptions the method actually needs;
4. compatibility with the current runtime and regression suite.

A newer paper is not automatically better for a different problem setting, and a larger research branch is not automatically more advanced.

## Selected stack

| Layer | Canonical implementation | Why this version wins |
| --- | --- | --- |
| CATE | Hybrid cross-fitted DR learner | combines group-aware cross-fitting, pluggable nuisance/effect models, strict propensity semantics, second-stage OOF uncertainty, and Mahalanobis distributional support |
| OPE | Cross-fitted beta*-IPS flagship + estimator panel | beta*-IPS is the primary low-variance additive-control-variate estimator; beta is cross-fitted by default to avoid same-sample plug-in bias; DR/IPS/SNIPS/SWITCH-DR/DR-OS remain robustness comparators |
| OPE uncertainty | IID or protocol-defined cluster-robust SE | repeated observations can use defensible experiment clusters instead of pretending rows are independent |
| OPE combination | Meta-OPE / BLUE-style diagnostic | correlated estimator combination is exposed as an efficiency diagnostic, not silently promoted as exact finite-sample evidence |
| Safe PI | Calibrated support-anchored feasible policy search | consumes real lower/upper bounds when available, fails closed on missing support in explicit mode, and ranks every final feasible candidate instead of clipping a raw argmax afterwards |
| Proposal policy | Optional SPIBB-style support anchoring | a learned proposal may be evaluated, but unsupported action probability cannot increase; proposal search never replaces the safer per-action candidates |
| Long horizon | stochastic rollout + downside CVaR | ranks policies by downside return and constraint violation rather than mean reward alone |
| Credit | dynamics-aware GAE | true dynamics boundaries stop recursive credit; ordinary export/window boundaries do not alter the learning target |
| Sequential offline RL | backend-neutral KuaiRand export | CQL/IQL/Decision Transformer remain external research backends because no single offline-RL learner is universally best across support/action-space regimes |

## 1. CATE: hybrid DR rather than old branch vs main

The stale research branch had stronger *estimation semantics* than the old main implementation:

- optional `group_id` so repeated users/units stay in one cross-fitting fold;
- balanced group-aware folds;
- pluggable nuisance and second-stage regressors;
- strict pairwise positivity;
- practical overlap separated from numerical propensity clipping;
- explicit clipping-rate diagnostics.

The evolved main implementation had stronger *distribution-shift semantics*:

- second-stage out-of-fold residual scale rather than in-sample effect residuals;
- regularized Mahalanobis distance;
- support radius estimated from the training distribution;
- uncertainty inflation and support decay away from the training manifold.

The canonical implementation now contains both. Ridge regression is retained only as a dependency-free auditable backend. It is not treated as the predictive performance ceiling; nonlinear / tree / neural nuisance and effect models can be injected without changing the cross-fitting contract.

### Important separation

`strict positivity`, `practical overlap`, and `propensity clipping` are different concepts.

- Positivity is an identification requirement.
- Practical overlap is an evidence/support diagnostic.
- Clipping is an explicit numerical stabilization choice.

The default learner therefore does not silently clip propensities.

## 2. OPE: cross-fitted beta*-IPS is the flagship estimator

The repository previously had two partially competing OPE directions:

- current main: IPS / DR / beta*-IPS with strong overlap diagnostics;
- stale research branch: DM / SNIPS / DR / SWITCH-DR / DR optimistic shrinkage / cluster uncertainty, but without the strongest beta*-IPS default semantics.

The canonical stack combines them without treating all estimators as equally preferred.

### Primary estimator

`beta_ips` uses the variance-minimizing additive control variate with `w - 1`, but the beta coefficient is now **cross-fitted by default**. Each evaluation fold is corrected using a beta estimated without that fold.

This follows the 2026 beta*-IPS direction while addressing the finite-sample same-sample plug-in bias discussed in that work. A fixed beta estimated on an independent tuning cohort is also supported for strict holdout evaluation.

The same-sample beta*-IPS estimate remains available only as a diagnostic/reproduction field.

### Robustness panel

The same evaluation returns:

- Direct Method;
- IPS;
- self-normalized IPS;
- Doubly Robust;
- SWITCH-DR;
- optimistic DR shrinkage / DR-OS;
- cross-fitted beta*-IPS;
- same-sample beta*-IPS diagnostic;
- Meta-OPE / BLUE-style combination diagnostic.

SWITCH-DR thresholds and DR-OS shrinkage parameters are experiment hyperparameters and must be selected without final-test leakage.

### Why Meta-OPE is not the promotion default

The BLUE-style combination can improve statistical efficiency when estimators are correlated, but the current implementation estimates its covariance-combination weights on the evaluation cohort. It is therefore exposed as an efficiency diagnostic. Promotion remains anchored to an independently calibrated evidence protocol rather than pretending the plug-in combination has an exact finite-sample guarantee.

## 3. Safe policy improvement: calibrated bounds + final-feasible ranking

Two older implementations each solved only half of the problem.

The evolved main implementation correctly evaluated each action **after** TV/cost feasibility constraints. This prevents an action with the highest raw lower bound but almost zero feasible update mass from hiding a slightly lower-valued action that can actually be deployed safely.

The stale branch was stronger about evidence semantics: it could consume supplied lower/upper bounds and explicit support rather than automatically interpreting generic model uncertainty as a confidence interval.

The canonical implementation now has both properties.

### Strong mode

Use:

```text
bound_mode = provided
support_mode = explicit
```

Then every action value must carry an upstream lower bound and every constrained cost must carry an upper bound. These may come from one-sided conformal calibration, causal inference, a variance-adaptive confidence procedure, or another protocol whose assumptions are explicit.

Missing treatment support fails closed in explicit mode.

### Reference compatibility mode

`gaussian_reference` remains available for deterministic synthetic tests and backwards compatibility. It computes `value - z * uncertainty` and `cost + z * uncertainty`, but the code and documentation do not claim that arbitrary model residuals are causal confidence intervals.

### Candidate search

The improver evaluates:

1. every supported single-action direction;
2. optionally, a learned proposal after support anchoring.

Each direction is interpolated from the behavior policy only as far as allowed by:

- total-variation trust region;
- hard expected-cost constraint;
- minimum final pessimistic improvement.

The final policy is selected by constrained pessimistic policy value.

## 4. What is deliberately not merged just because it is newer

### Betting / freezing confidence procedures

Recent second-order contextual-bandit work develops betting-style, variance-adaptive confidence bounds and freezing. Those ideas are attractive for small-sample policy selection, but they require their exact assumptions and confidence construction. GrowthEvo's Safe PI is therefore designed to **consume** such provided bounds without fabricating an approximate imitation from residual standard deviations.

### Online pessimistic policy learning

Recent online/adaptive pessimistic contextual-bandit methods address sequential data collection and fast regret. GrowthEvo's current Safe PI kernel is an offline deployment-improvement layer over logged behavior. An online regret algorithm should be added only with a real online collection protocol rather than renamed and inserted into an offline API.

### One universal CATE learner

There is no defensible single universally best S/T/X/R/DR/forest/neural CATE learner across all overlap, sample-size, and heterogeneity regimes. GrowthEvo therefore makes the orthogonal cross-fitting contract canonical and the predictive backend pluggable. Benchmark selection decides the backend; the causal protocol does not hard-code one model family.

## 5. Evidence and performance rule

A method is not promoted because its paper is newer or its point estimate is larger.

For a candidate algorithm change to replace the canonical implementation, it should satisfy all applicable checks:

```text
statistical assumptions are explicit
no new train/evaluation or temporal leakage
support / overlap semantics are not weakened
synthetic ground-truth regression does not degrade
real-data protocol can reproduce the claimed metric
uncertainty is calibrated to the quantity it claims to bound
hard safety fallbacks remain available
Python 3.11 and 3.12 full CI pass
runtime and training demos pass
```

For real-data performance comparisons, report estimator/model selection on validation data and final metrics on an untouched evaluation split. Do not choose the winning algorithm from final-test error and then report that same final-test error as unbiased evidence.

## Research directions represented in this selection

The current stack is informed by the following research directions rather than by branch age:

- additive control variates / beta*-IPS for efficient OPE (SIGIR 2026);
- correlated-estimator Meta-OPE / BLUE-style efficiency (RecSys 2025);
- variance-adaptive second-order contextual-bandit confidence and freezing (COLT 2025);
- decision-point / support-restricted safe policy improvement (AISTATS 2025 direction);
- modern orthogonal / doubly robust heterogeneous-treatment estimation with cross-fitting;
- downside-CVaR model-based planning and dynamics-aware long-horizon credit.

The exact theorem from a paper should be claimed only when its assumptions and estimator are actually implemented. "Frontier" in GrowthEvo therefore means **newest defensible method for this contract**, not newest citation pasted into the README.
