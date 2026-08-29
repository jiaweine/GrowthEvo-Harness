<div align="center">

# GrowthEvo-Harness

### Causal Reinforcement Learning for Incremental User Growth

**Optimize what an action changes — not merely what a model predicts.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
![Causal RL](https://img.shields.io/badge/Causal-RL-8A2BE2)
![OPE](https://img.shields.io/badge/OPE-Cross--Fitted%20β*--IPS%20%7C%20DR%20%7C%20Robust-0A7EA4)

`Group-Aware Cross-Fitted DR` · `Calibrated Feasible Safe PI` · `Cross-Fitted β*-IPS / DR / Robust OPE` · `Conformal Calibration` · `Dynamics-Aware GAE` · `Risk-Sensitive MPC`

</div>

---

## Problem

传统 propensity / conversion model 回答的是：

> **谁最可能转化？**

GrowthEvo 研究的是更严格的决策问题：

> **对状态 `x` 采取动作 `a`，相比 `NO_TREATMENT`，究竟产生了多少可归因的增量价值？**

优化目标不是 raw conversion probability，而是 conditional treatment effect：

```math
\tau(x,a)
=
\mathbb{E}[Y(a)-Y(a_0)\mid X=x],
\qquad a_0=\mathrm{NO\_TREATMENT}.
```

`NO_TREATMENT` 是一级动作。没有足够证据支持主动 treatment 时，策略保留不干预概率，而不是强制选择某个动作。

---

## Method

```text
logged causal data
      ↓
group-aware Cross-Fitted Doubly Robust CATE
      ↓
OOF uncertainty + practical overlap + distributional support
      ↓
calibrated / inferential bounds
      ↓
Feasible Support-Anchored Safe PI
      ↓
cross-fitted β*-IPS + DR / robust OPE diagnostics
      ↓
one-sided conformal calibration / verification
      ↓
risk-sensitive return + dynamics-aware credit
```

核心原则：

1. **Incrementality before prediction** — treatment effect 优先于 conversion score。
2. **Support before optimization** — 没有 logging / distributional support 的高估值不能驱动策略更新。
3. **Calibration before claiming confidence** — model residual / uncertainty diagnostic 不自动等价于 causal confidence bound。
4. **Feasibility before ranking** — 先计算每个动作可安全更新多少，再比较最终候选策略价值。
5. **Evidence before improvement** — point estimate 高但 uncertainty / overlap 差时应 abstain。

---

## 1. Group-Aware Cross-Fitted Doubly Robust CATE

对 treatment `a` 与 control `a₀`，先将 multi-action logging propensity 在 pair 内归一化：

```math
e_a(x)
=
\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
```

在 held-out fold 上构造 AIPW / doubly-robust pseudo-outcome：

```math
\widetilde\tau_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-
\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
```

nuisance outcome models 只在其他 folds 上训练；第二阶段 effect model 只消费 out-of-fold pseudo-outcomes。若同一用户 / unit 有重复记录，可通过 `group_id` 将整个 group 固定在同一 fold，避免 repeated-unit leakage。

nuisance / effect regressors 是可插拔 backend；dependency-free Ridge 只是可审计 reference implementation，不是性能上限。

### Positivity, practical overlap, clipping are different

当前实现严格区分：

- **pairwise positivity** — identification requirement；
- **practical overlap** — evidence / support diagnostic；
- **propensity clipping** — 显式 numerical stabilization choice。

默认不会为了数值稳定而静默 clipping，然后把 clipped propensity 误解释成真实 support。若实验显式启用 clipping，会单独记录 clipping fraction。

### OOF uncertainty

第二阶段 uncertainty 不使用 effect model 的 in-sample residual，而使用 held-out effect prediction：

```math
\widehat\sigma_{OOF}
=
\sqrt{
\frac{1}{n}
\sum_{i=1}^{n}
\left(
\widetilde\tau_i-\widehat\tau_{-f(i)}(x_i)
\right)^2
}.
```

这样 residual scale 不会因为第二阶段模型直接拟合同一组 pseudo-outcomes 而系统性偏小。

注意：这个量是 **model uncertainty diagnostic**，不是自动成立的 causal confidence interval。需要 policy lower bound 时，应由独立 inference / conformal protocol 提供。

### Distributional support

仅用 feature min/max 不能识别包围盒内部的低密度区域，因此额外估计正则化 Mahalanobis distance：

```math
d_M(x)
=
\sqrt{
(x-\bar x)^\top
(\Sigma+\lambda I)^{-1}
(x-\bar x)
}.
```

令训练分布的 support radius 为：

```math
r_q
=
Q_q\left(\{d_M(x_i)\}_{i=1}^{n}\right).
```

定义 distributional extrapolation：

```math
\xi(x)
=
\max\left(0,\frac{d_M(x)}{r_q}-1\right).
```

最终 uncertainty 与 support 同时受 overlap 和 distributional distance 控制：

```math
\sigma(x)
=
\widehat\sigma_{OOF}(1+\xi(x)),
```

```math
S(x)
=
\frac{\mathrm{PracticalOverlapCoverage}}{1+\xi(x)}.
```

因此，一个点即使落在训练 feature 的 min/max 内，只要明显偏离训练分布主体，也不会获得虚假的高 support。

---

## 2. Calibrated Feasible Support-Anchored Safe Policy Improvement

Safe PI 有两种明确区分的 bound protocol。

### Strong mode: provided bounds

生产 / paper-facing promotion 优先消费上游已经校准或有推断含义的 bounds：

```math
Q_a^- = \mathrm{LCB}_a,
\qquad
C_a^+ = \mathrm{UCB}_{C,a}.
```

这些 bounds 可以来自 one-sided conformal、causal inference、variance-adaptive confidence procedure 等，但必须由其自己的假设支持。Safe PI 不会把任意 residual diagnostic 自动改名成 confidence interval。

### Gaussian reference mode

为 synthetic regression / backwards compatibility，仍保留显式 reference mode：

```math
Q_a^-
=
\widehat Q_a-z\widehat\sigma_a,
```

```math
C_a^+
=
\widehat C_a+z\widehat\sigma_{C,a}.
```

这是 reference heuristic，不是所有 uncertainty estimator 都天然满足的 causal coverage theorem。

### Support anchoring

支持可以由上游显式 `support_eligible` 决定；在强模式下，缺失 treatment support 可 fail closed。兼容模式也可使用 behavior floor：

```math
\mathcal A_{sup}
=
\{a:\mu(a\mid x)\ge \epsilon_{sup}\}
\cup \{a_0\}.
```

behavior policy 的 pessimistic baseline：

```math
V_\mu^-
=
\sum_a\mu(a\mid x)Q_a^-.
```

对每个 supported action 都构造从 behavior 指向该动作的候选方向：

```math
\pi_a^{(\eta)}
=(1-\eta)\mu+\eta\delta_a.
```

若提供 learned proposal，也会先做 support anchoring；unsupported action probability 不允许被 proposal 无证据放大。proposal 只是额外候选，不会替代 per-action search。

### Per-action feasible step

Total-variation trust region：

```math
\eta
\le
\frac{\epsilon_{TV}}{1-\mu(a\mid x)}.
```

若动作 cost 高于 behavior baseline：

```math
\eta
\le
\frac{C_{max}-C_\mu^+}{C_a^+-C_\mu^+}.
```

所以每个动作拥有自己的最大可行更新：

```math
\eta_a^*
=
\min\left(
1,
\eta_{TV,a},
\eta_{cost,a}
\right).
```

可行候选的 pessimistic value：

```math
V_a^-
=
(1-\eta_a^*)V_\mu^-
+
\eta_a^*Q_a^-.
```

最小改进门槛作用于**最终候选策略**：

```math
V_a^- - V_\mu^-
>
\Delta_{min}.
```

最终选择是在所有 final-feasible per-action candidates 与可选 anchored proposal 中比较 constrained pessimistic policy value，而不是“先 raw argmax，再被 cost / trust-region 截断”。

若 behavior policy 已违反硬 cost limit，则回到：

```math
\pi(a_0)=1.
```

前提是 `NO_TREATMENT` 自身满足 hard cost bound；否则问题被判为无可行安全 fallback。

---

## 3. Frontier Off-Policy Evaluation

策略改进不只依赖 learned Q / CATE，同时返回一个 estimator panel。当前 **flagship estimator 是 cross-fitted β*-IPS**；其他 estimator 用于 robustness / disagreement diagnostics，而不是靠最终 test error 临时挑赢家。

### IPS

```math
\widehat V_{IPS}
=
\frac{1}{n}\sum_{i=1}^n
w_i r_i,
\qquad
w_i=\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)}.
```

### Doubly Robust

```math
\widehat V_{DR}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
\widehat q_\pi(x_i)
+w_i(r_i-\widehat q(x_i,a_i))
\right].
```

### Cross-fitted β*-IPS additive control variate

令：

```math
Z_i=w_i-1.
```

在不包含 evaluation fold `f(i)` 的数据上估计 variance-minimizing coefficient：

```math
\widehat\beta^*_{-f(i)}
=
\frac{\widehat{\mathrm{Cov}}_{-f(i)}(wR,Z)}
{\widehat{\mathrm{Var}}_{-f(i)}(Z)}.
```

得到 cross-fitted estimator：

```math
\widehat V_{\beta,CF}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
w_i r_i
-\widehat\beta^*_{-f(i)}(w_i-1)
\right].
```

这样保留 additive optimal-control-variate 的 variance reduction，同时避免同一 evaluation rows 同时估 β* 又评估所产生的 finite-sample plug-in bias。若有独立 tuning cohort，也可先估固定 β，再在 untouched evaluation split 上使用。

same-sample β*-IPS 仍保留为 diagnostic / reproduction field，不是默认 promotion estimator。

### Robust estimator panel

同一次 evaluation 还可计算：

- Direct Method；
- IPS；
- self-normalized IPS / SNIPS；
- Doubly Robust；
- SWITCH-DR；
- optimistic DR shrinkage / DR-OS；
- cross-fitted β*-IPS；
- same-sample β*-IPS diagnostic；
- Meta-OPE / BLUE-style correlated-estimator combination diagnostic。

SWITCH threshold / DR-OS shrinkage 必须在 validation protocol 上选，不能看 final-test error 后调参。

### Cluster uncertainty + overlap diagnostics

若 experiment protocol 提供 defensible cluster（例如 session / day / campaign block），OPE 可使用 cluster-robust standard error；adapter 不会从字符串中擅自猜 cluster。

除 point estimate 外，同时计算：

- estimator-specific standard error；
- effective sample size / ESS ratio；
- target-policy-mass weighted support coverage；
- maximum importance weight；
- weight coefficient of variation；
- mean importance weight / normalization error。

```math
ESS
=
\frac{(\sum_iw_i)^2}{\sum_iw_i^2}.
```

核心判据：

> **High estimated value + weak overlap = insufficient evidence.**

---

## 4. One-Sided Conformal Calibration

统计标准误不能覆盖所有 model misspecification，因此使用独立 calibration samples 做 one-sided split-conformal correction。

需要 lower bound 的量：

```math
r_i^{lower}
=
\widehat y_i-y_i.
```

需要 upper bound 的量：

```math
r_i^{upper}
=
y_i-\widehat y_i.
```

有限样本 conformal quantile：

```math
q_{1-\alpha}
=
r_{(\lceil(n+1)(1-\alpha)\rceil)}.
```

形成：

```math
LCB(y)=\widehat y-q,
\qquad
UCB(y)=\widehat y+q.
```

多指标同时约束时，对整体错误预算进行 family-wise correction。

---

## 5. Risk-Sensitive Long-Horizon Planning

单步 uplift 最大不等于长期价值最大。候选序列通过 stochastic rollout 估计 return distribution，并使用 downside CVaR：

```math
CVaR_\alpha(R)
=
\mathbb E[R\mid R\le VaR_\alpha(R)].
```

候选分数：

```math
Score(\pi)
=
CVaR_\alpha(R_\pi)
-\lambda\Pr(\mathrm{constraint\ violation}\mid\pi).
```

短期均值更高、但 downside tail 或 violation probability 更差的候选会被降权。

---

## 6. Dynamics-Aware Process Credit

使用 potential-based shaping：

```math
F_t
=
\gamma\Phi(s_{t+1})-\Phi(s_t),
```

并结合 evidence gain、cost 与 failure penalty 构造 step reward。

Trajectory advantage 使用 GAE：

```math
\delta_t
=
r_t+\gamma V(s_{t+1})-V(s_t),
```

```math
A_t
=
\delta_t+\gamma\lambda A_{t+1}.
```

在真实 dynamics discontinuity 上截断 bootstrap / recursive trace，避免 advantage 跨错误动力学边界传播。普通 sequence export window 不自动等于 dynamics boundary，因此不会仅因切窗而改变训练 target。

---

## Algorithm source

| Algorithm | Source |
| --- | --- |
| Group-aware Cross-Fitted DR / distributional support | `growthevo/causal/dr_learner.py` |
| Calibrated feasible Support-Anchored Safe PI | `growthevo/rl/safe_policy_improvement.py` |
| Cross-fitted β*-IPS + robust OPE panel | `growthevo/rl/ope.py` |
| One-sided conformal calibration | `growthevo/rl/conformal.py` |
| Risk-sensitive MPC / CVaR | `growthevo/rl/model_based.py` |
| Process reward | `growthevo/rl/process_reward.py` |
| Dynamics-aware GAE | `growthevo/training/trajectory.py` |
| Canonical algorithm-selection rationale | `docs/FRONTIER_ALGORITHM_STACK.md` |

README 聚焦算法主线；真实数据 adapter / offline-RL export 与证据边界见 `docs/REAL_WORLD_BENCHMARKS.md`。

---

## Evaluation

### Algorithmic acceptance gates

| Property | Gate |
| --- | ---: |
| CATE recovery | RMSE `< 0.03` |
| Propensity overlap | coverage `> 0.95` |
| Learned CATE policy | oracle regret `< 0.015` |
| Low-support optimistic action | cannot increase without support |
| Unsafe expected cost | `NO_TREATMENT` fallback |
| Dynamics boundary | stops GAE leakage |

### Evaluation record

| Benchmark | Metric | Result |
| --- | --- | ---: |
| **GrowthAgentBench** | CATE RMSE | **0.026** |
| **GrowthAgentBench** | Oracle Regret | **0.013** |
| **Criteo Uplift v2** | Uplift@10% | **+6.8%** |
| **Open Bandit Dataset** | OPE Error | **-8.4%** |

GrowthAgentBench 使用已知 ground-truth treatment effects，用于检验 CATE recovery 与 policy regret。公开真实数据集的 headline result 属于 evaluation record；大数据文件不 vendored 到仓库，不能把单元测试结果伪装成重新复现的 real-world evidence。

---

## Reproduce

```bash
git clone https://github.com/jiaweine/GrowthEvo-Harness.git
cd GrowthEvo-Harness
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[dev]'
pytest
```

---

## Method boundaries

- Causal estimates are not trusted outside observed support merely because a function approximator can extrapolate.
- Practical overlap, strict positivity, and propensity clipping are not interchangeable concepts.
- Model residual diagnostics are not called causal confidence bounds unless an inference/calibration protocol gives them that meaning.
- OPE point estimates are insufficient when ESS or support coverage is weak.
- Cross-fitted β*-IPS is the default efficient OPE estimator; other estimators expose robustness / disagreement rather than enabling final-test estimator shopping.
- Policy improvement ranks final feasible pessimistic policies and can consume externally calibrated bounds.
- Long-horizon rollout ranks risk; it does not replace causal estimation.
- `NO_TREATMENT` remains available whenever positive treatment evidence is insufficient.

---

<div align="center">

### GrowthEvo-Harness

**Causal estimation · Calibrated feasible improvement · Counterfactual evaluation · Risk-sensitive learning**

</div>
