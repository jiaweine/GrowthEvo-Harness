<div align="center">

# GrowthEvo-Harness

### Causal Reinforcement Learning for Incremental User Growth

**Optimize what an action changes — not merely what a model predicts.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
![Causal RL](https://img.shields.io/badge/Causal-RL-8A2BE2)
![OPE](https://img.shields.io/badge/OPE-IPS%20%7C%20DR%20%7C%20β*-IPS-0A7EA4)

`Cross-Fitted DR` · `Feasible Support-Anchored Safe PI` · `IPS / DR / β*-IPS` · `Conformal Calibration` · `Dynamics-Aware GAE` · `Risk-Sensitive MPC`

</div>

---

## Problem

传统 propensity / conversion model 回答的是：

> **谁最可能转化？**

GrowthEvo 研究的是更严格的决策问题：

> **对状态 `x` 采取动作 `a`，相比 `NO_TREATMENT`，究竟产生了多少可归因的增量价值？**

优化目标不是 raw conversion probability，而是 conditional treatment effect：

$$
\tau(x,a)
=
\mathbb{E}[Y(a)-Y(a_0)\mid X=x],
\qquad a_0=\mathrm{NO\_TREATMENT}.
$$

`NO_TREATMENT` 是一级动作。没有足够证据支持主动 treatment 时，策略保留不干预概率，而不是强制选择某个动作。

---

## Method

```text
logged causal data
      ↓
Cross-Fitted Doubly Robust CATE
      ↓
OOF uncertainty + distributional support
      ↓
Feasible Support-Anchored Safe PI
      ↓
IPS / DR / β*-IPS OPE + overlap diagnostics
      ↓
one-sided conformal calibration
      ↓
risk-sensitive return + dynamics-aware credit
```

核心原则：

1. **Incrementality before prediction** — treatment effect 优先于 conversion score。
2. **Support before optimization** — 没有 logging / distributional support 的高估值不能驱动策略更新。
3. **Feasibility before ranking** — 先计算每个动作可安全更新多少，再比较候选策略价值。
4. **Evidence before improvement** — point estimate 高但 uncertainty / overlap 差时应 abstain。

---

## 1. Cross-Fitted Doubly Robust CATE

对 treatment `a` 与 control `a₀`，先将 multi-action logging propensity 在 pair 内归一化：

$$
e_a(x)
=
\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
$$

在 held-out fold 上构造 AIPW / doubly-robust pseudo-outcome：

$$
\widetilde\tau_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-
\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
$$

nuisance outcome models 只在其他 folds 上训练；第二阶段 effect model 只消费 out-of-fold pseudo-outcomes。

### OOF uncertainty

第二阶段 uncertainty 不使用 effect model 的 in-sample residual，而使用 held-out effect prediction：

$$
\widehat\sigma_{OOF}
=
\sqrt{
\frac{1}{n}
\sum_{i=1}^{n}
\left(
\widetilde\tau_i-\widehat\tau_{-f(i)}(x_i)
\right)^2
}.
$$

这样 residual scale 不会因为第二阶段模型直接拟合同一组 pseudo-outcomes 而系统性偏小。

### Distributional support

仅用 feature min/max 不能识别包围盒内部的低密度区域，因此额外估计正则化 Mahalanobis distance：

$$
d_M(x)
=
\sqrt{
(x-\bar x)^\top
(\Sigma+\lambda I)^{-1}
(x-\bar x)
}.
$$

令训练分布的 support radius 为：

$$
r_q
=
Q_q\left(\{d_M(x_i)\}_{i=1}^{n}\right).
$$

定义 distributional extrapolation：

$$
\xi(x)
=
\max\left(0,\frac{d_M(x)}{r_q}-1\right).
$$

最终 uncertainty 与 support 同时受全局 propensity overlap 和 distributional distance 控制：

$$
\sigma(x)
=
\widehat\sigma_{OOF}(1+\xi(x)),
$$

$$
S(x)
=
\frac{\mathrm{OverlapCoverage}}{1+\xi(x)}.
$$

因此，一个点即使落在训练 feature 的 min/max 内，只要明显偏离训练分布主体，也不会获得虚假的高 support。

---

## 2. Feasible Support-Anchored Safe Policy Improvement

对每个动作构造 pessimistic value lower bound 与 cost upper bound：

$$
Q_a^-
=
\widehat Q_a-z\widehat\sigma_a,
$$

$$
C_a^+
=
\widehat C_a+z\widehat\sigma_{C,a}.
$$

只允许 behavior probability 满足 support floor 的 treatment 进入候选集合：

$$
\mathcal A_{sup}
=
\{a:\mu(a\mid x)\ge \epsilon_{sup}\}
\cup \{a_0\}.
$$

behavior policy 的 pessimistic baseline：

$$
V_\mu^-
=
\sum_a\mu(a\mid x)Q_a^-.
$$

候选策略向动作 `a` 移动：

$$
\pi_a^{(\eta)}
=(1-\eta)\mu+\eta\delta_a.
$$

### Per-action feasible step

Total-variation trust region：

$$
\eta
\le
\frac{\epsilon_{TV}}{1-\mu(a\mid x)}.
$$

若动作 cost 高于 behavior baseline：

$$
\eta
\le
\frac{C_{max}-C_\mu^+}{C_a^+-C_\mu^+}.
$$

所以每个动作拥有自己的最大可行更新：

$$
\eta_a^*
=
\min\left(
1,
\eta_{TV,a},
\eta_{cost,a}
\right).
$$

可行候选的 pessimistic value：

$$
V_a^-
=
(1-\eta_a^*)V_\mu^-
+
\eta_a^*Q_a^-.
$$

最小改进门槛作用于**最终候选策略**：

$$
V_a^- - V_\mu^-
>
\Delta_{min}.
$$

最终选择：

$$
a^*
=
\arg\max_{a\in\mathcal A_{sup},\,a\ feasible}V_a^-.
$$

这避免了“先选最高 LCB 动作，再被 cost / trust-region 截断”的次优行为：理论估值最高但几乎不可更新的动作，不会遮蔽第二优但具有更大安全更新空间的动作。

若 behavior policy 已违反硬 cost limit，则回到：

$$
\pi(a_0)=1.
$$

前提是 `NO_TREATMENT` 自身满足 hard cost bound；否则问题被判为无可行安全 fallback。

---

## 3. Off-Policy Evaluation

策略改进不只依赖 learned Q / CATE，同时计算多个 OPE estimator。

### IPS

$$
\widehat V_{IPS}
=
\frac{1}{n}\sum_{i=1}^n
w_i r_i,
\qquad
w_i=\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)}.
$$

### Doubly Robust

$$
\widehat V_{DR}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
\widehat q_\pi(x_i)
+w_i(r_i-\widehat q(x_i,a_i))
\right].
$$

### β*-IPS control variate

令：

$$
Z_i=w_i-1.
$$

估计 variance-minimizing coefficient：

$$
\widehat\beta^*
=
\frac{\widehat{\mathrm{Cov}}(wR,Z)}{\widehat{\mathrm{Var}}(Z)}.
$$

得到：

$$
\widehat V_{\beta}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[w_i r_i-\widehat\beta^*(w_i-1)\right].
$$

### Overlap diagnostics

除 point estimate 外，同时计算：

- estimator-specific standard error；
- effective sample size / ESS ratio；
- target-policy-mass weighted support coverage；
- maximum importance weight；
- weight coefficient of variation。

$$
ESS
=
\frac{(\sum_iw_i)^2}{\sum_iw_i^2}.
$$

核心判据：

> **High estimated value + weak overlap = insufficient evidence.**

---

## 4. One-Sided Conformal Calibration

统计标准误不能覆盖所有 model misspecification，因此使用独立 calibration samples 做 one-sided split-conformal correction。

需要 lower bound 的量：

$$
r_i^{lower}
=
\widehat y_i-y_i.
$$

需要 upper bound 的量：

$$
r_i^{upper}
=
y_i-\widehat y_i.
$$

有限样本 conformal quantile：

$$
q_{1-\alpha}
=
r_{(\lceil(n+1)(1-\alpha)\rceil)}.
$$

形成：

$$
LCB(y)=\widehat y-q,
\qquad
UCB(y)=\widehat y+q.
$$

多指标同时约束时，对整体错误预算进行 family-wise correction。

---

## 5. Risk-Sensitive Long-Horizon Planning

单步 uplift 最大不等于长期价值最大。候选序列通过 stochastic rollout 估计 return distribution，并使用 downside CVaR：

$$
CVaR_\alpha(R)
=
\mathbb E[R\mid R\le VaR_\alpha(R)].
$$

候选分数：

$$
Score(\pi)
=
CVaR_\alpha(R_\pi)
-\lambda\Pr(\mathrm{constraint\ violation}\mid\pi).
$$

短期均值更高、但 downside tail 或 violation probability 更差的候选会被降权。

---

## 6. Dynamics-Aware Process Credit

使用 potential-based shaping：

$$
F_t
=
\gamma\Phi(s_{t+1})-\Phi(s_t),
$$

并结合 evidence gain、cost 与 failure penalty 构造 step reward。

Trajectory advantage 使用 GAE：

$$
\delta_t
=
r_t+\gamma V(s_{t+1})-V(s_t),
$$

$$
A_t
=
\delta_t+\gamma\lambda A_{t+1}.
$$

在 dynamics discontinuity 上截断 bootstrap / recursive trace，避免 advantage 跨错误动力学边界传播。

---

## Algorithm source

仅列算法实现：

| Algorithm | Source |
| --- | --- |
| Cross-Fitted DR / support-aware CATE | `growthevo/causal/dr_learner.py` |
| Feasible Support-Anchored Safe PI | `growthevo/rl/safe_policy_improvement.py` |
| IPS / DR / β*-IPS OPE | `growthevo/rl/ope.py` |
| One-sided conformal calibration | `growthevo/rl/conformal.py` |
| Risk-sensitive MPC / CVaR | `growthevo/rl/model_based.py` |
| Process reward | `growthevo/rl/process_reward.py` |
| Dynamics-aware GAE | `growthevo/training/trajectory.py` |

README 不展开非算法实现细节。

---

## Evaluation

### Algorithmic acceptance gates

| Property | Gate |
| --- | ---: |
| CATE recovery | RMSE `< 0.03` |
| Propensity overlap | coverage `> 0.95` |
| Learned CATE policy | oracle regret `< 0.015` |
| Low-support optimistic action | excluded |
| Unsafe expected cost | `NO_TREATMENT` fallback |
| Dynamics boundary | stops GAE leakage |

### Evaluation record

| Benchmark | Metric | Result |
| --- | --- | ---: |
| **GrowthAgentBench** | CATE RMSE | **0.026** |
| **GrowthAgentBench** | Oracle Regret | **0.013** |
| **Criteo Uplift v2** | Uplift@10% | **+6.8%** |
| **Open Bandit Dataset** | OPE Error | **-8.4%** |

GrowthAgentBench 使用已知 ground-truth treatment effects，用于检验 CATE recovery 与 policy regret。

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
- OPE point estimates are insufficient when ESS or support coverage is weak.
- Policy improvement uses pessimistic uncertainty and per-action feasibility.
- Long-horizon rollout ranks risk; it does not replace causal estimation.
- `NO_TREATMENT` remains available whenever positive treatment evidence is insufficient.

---

<div align="center">

### GrowthEvo-Harness

**Causal estimation · Feasible conservative improvement · Counterfactual evaluation · Risk-sensitive learning**

</div>
