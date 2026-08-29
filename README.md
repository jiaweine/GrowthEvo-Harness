<div align="center">

# GrowthEvo-Harness

### Causal Reinforcement Learning for Incremental User Growth

**Optimize what an action changes — not merely what a model predicts.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
![Causal RL](https://img.shields.io/badge/Causal-RL-8A2BE2)
![OPE](https://img.shields.io/badge/OPE-Cross--Fitted%20β*--IPS%20%7C%20DR%20%7C%20Robust-0A7EA4)
![Evidence](https://img.shields.io/badge/Evidence-Pre--Registered%20%7C%20Locked-2E8B57)

`Group-Aware Cross-Fitted DR` · `Calibrated Feasible Safe PI` · `Cross-Fitted β*-IPS` · `Pre-Registered Locked Evaluation` · `Risk-Sensitive MPC` · `Dynamics-Aware GAE`

</div>

---

## What GrowthEvo optimizes

普通 propensity / conversion model 回答：

> **谁最可能转化？**

GrowthEvo 研究的是更严格的问题：

> **对状态 `x` 采取动作 `a`，相比 `NO_TREATMENT`，究竟产生了多少可归因的增量价值？**

核心对象是 conditional treatment effect：

```math
\tau(x,a)
=
\mathbb{E}[Y(a)-Y(a_0)\mid X=x],
\qquad a_0=\mathrm{NO\_TREATMENT}.
```

`NO_TREATMENT` 是一级动作。没有足够支持、校准或反事实证据时，系统允许 abstain / holdout，而不是强迫选一个 treatment。

---

## Canonical frontier stack

```text
logged causal / bandit data
        ↓
group-aware cross-fitting
        ↓
Doubly Robust CATE + pluggable nuisance/effect learners
        ↓
strict positivity + practical overlap + distributional support
        ↓
calibrated / inferential lower & upper bounds
        ↓
final-feasible Support-Anchored Safe PI
        ↓
cross-fitted β*-IPS + robust OPE estimator panel
        ↓
pre-register source / split / Q / candidates / evidence gates
        ↓
materialize evidence + validate realized manifest
        ↓
evidence eligibility → validation selection → frozen final holdout
        ↓
conformal verification + risk-sensitive planning
        ↓
dynamics-aware trajectory credit
```

设计原则：

1. **Incrementality before prediction** — uplift / causal effect 优先于 raw conversion score。
2. **Support before optimization** — function approximator 能外推，不代表数据支持该动作。
3. **Calibration before confidence** — model residual 不是自动成立的 causal confidence interval。
4. **Feasibility before ranking** — 比较最终可执行策略，不比较被约束前的 raw action score。
5. **Evidence eligibility before estimator ranking** — weak-support point estimate 不能因为碰巧接近 reference 就赢。
6. **Validation before holdout** — estimator / hyperparameter 只能在 validation 上选；final test 不用于挑赢家。
7. **Pre-registration before validation** — 数据源、split、Q、候选集、gate 必须在 validation 打开前冻结。
8. **Artifact before promotion** — 没有完整 fingerprint chain 的数字不升级为当前 real-world claim。

---

## 1. Group-Aware Cross-Fitted Doubly Robust CATE

对于 treatment `a` 与 control `a₀`，multi-action logging propensity 先在 pair 内归一化：

```math
e_a(x)
=
\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
```

在 held-out fold 上构造 doubly-robust pseudo-outcome：

```math
\widetilde\tau_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-
\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
```

当前实现：

- repeated user / cluster 可通过 `group_id` 做 group-aware fold assignment；
- nuisance outcome learner 与 second-stage effect learner 都可替换；
- dependency-free Ridge 是 auditable reference backend，不是性能上限；
- **strict positivity**、**practical overlap**、**propensity clipping** 分开建模；
- 默认不靠隐式 clipping 把缺乏支持的数据伪装成稳定数据。

### OOF uncertainty

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

这是 model / extrapolation diagnostic，不自动宣称成 causal confidence interval。

### Distributional support

使用 regularized Mahalanobis distance 检测包围盒内部低密度区域：

```math
d_M(x)
=
\sqrt{
(x-\bar x)^\top
(\Sigma+\lambda I)^{-1}
(x-\bar x)
}.
```

令训练分布 support radius 为 `r_q`：

```math
\xi(x)
=
\max\left(0,\frac{d_M(x)}{r_q}-1\right),
```

```math
S(x)
=
\frac{\mathrm{OverlapCoverage}}{1+\xi(x)}.
```

所以“落在 feature min/max 内”不再等于“具有高数据支持”。

---

## 2. Calibrated Final-Feasible Safe Policy Improvement

强模式直接消费上游校准 / 推断得到的 pessimistic value 与 conservative cost：

```math
Q_a^- = L_a,
\qquad
C_a^+ = U_a.
```

历史 Gaussian 形式仅保留为 **reference mode**：

```math
Q_a^-
=
\widehat Q_a-z\widehat\sigma_a,
\qquad
C_a^+
=
\widehat C_a+z\widehat\sigma_{C,a}.
```

Generic model residual 不会默认包装成“真实置信区间”。

从 behavior policy `μ` 向动作 `a` 的 point-mass policy 移动：

```math
\pi_a^{(\eta)}
=(1-\eta)\mu+\eta\delta_a.
```

TV trust region：

```math
\eta
\le
\frac{\epsilon_{TV}}{1-\mu(a\mid x)}.
```

Cost constraint：

```math
\eta
\le
\frac{C_{max}-C_\mu^+}{C_a^+-C_\mu^+}.
```

系统比较每个动作 **截断后的 final-feasible policy value**，以及可选的 support-anchored learned proposal，而不是先 raw argmax 再事后裁剪。

若 behavior policy 已违反硬 cost limit 且 `NO_TREATMENT` 可行：

```math
\pi(a_0)=1.
```

---

## 3. Frontier Off-Policy Evaluation

默认 efficient estimator 是 **cross-fitted β*-IPS**。DM / IPS / SNIPS / DR / SWITCH-DR / DR-OS / Meta-OPE 同时暴露，用于 robustness、disagreement 与验证选择。

### Importance weight

```math
w_i
=
\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)}.
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

### Cross-fitted β*-IPS

令：

```math
Z_i=w_i-1.
```

β coefficient 只使用不包含当前 evaluation fold 的数据：

```math
\widehat\beta^*_{-f(i)}
=
\frac{\widehat{\mathrm{Cov}}_{-f(i)}(wR,Z)}
{\widehat{\mathrm{Var}}_{-f(i)}(Z)}.
```

最终：

```math
\widehat V_{\beta,CF}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
w_i r_i
-\widehat\beta^*_{-f(i)}(w_i-1)
\right].
```

same-sample β*-IPS 保留为 diagnostic，不是默认 policy-evidence estimator。

### Evidence diagnostics

同时报告：

- estimator-specific standard error；
- ESS / ESS ratio；
- target-policy-mass support coverage；
- maximum importance weight；
- mean importance weight / normalization error；
- weight coefficient of variation；
- protocol-defined cluster-robust SE（如果实验真的定义了 cluster）。

```math
ESS
=
\frac{(\sum_i w_i)^2}{\sum_i w_i^2}.
```

**High estimated value + weak support is insufficient evidence.**

---

## 4. Pre-Registered Locked Real-World Evaluation

真正回答“哪个 estimator / model 性能更好”时，不能在 final test 上把所有方法跑一遍再挑最好看的。

### OPE

`OPEExperimentPlan` 在 validation 打开前锁定：

- dataset source；
- policy direction；
- reward；
- split；
- Q model / folds；
- target-policy Monte Carlo count；
- seed；
- support floor；
- evidence gate；
- estimator/hyperparameter grid。

`growthevo-locked-ope` 的顺序是：

```text
plan + realized manifest agreement
        ↓
open validation
        ↓
evidence gate
        ↓
select winner
        ↓
freeze
        ↓
open holdout once
```

当前 OBD plan 的 evidence gate 要求：

- support coverage `>= 0.95`；
- ESS ratio `>= 0.05`；
- positive supported importance mass。

### Criteo-style targeting

`TargetingExperimentPlan` v2 在 validation 打开前锁定：

- dataset source 与 outcome；
- train / validation / final holdout split、split seed；
- treatment 与 selected top fraction；
- propensity protocol；
- score-generation protocol；
- complete candidate-name set；
- candidate-config fingerprint。

实际 score 数值仍进入 evidence fingerprint，因此候选名不变但模型预测变了，也不是同一次 evidence。Full Criteo runner 只在 training split 拟合候选；validation 选出赢家后，第二遍读取数据并且只给赢家生成 final holdout score。

### Fingerprint chain

最终 artifact 绑定：

```text
experiment plan
+ candidate config
+ realized export manifest
+ validation rows/predictions
+ holdout rows/frozen predictions
+ evidence gate / candidate protocol
+ code commit SHA
```

这解决的是可审计性与 test-set shopping，不是假装“代码无法被恶意 fork”的密码学承诺。

---

## 5. One-Sided Conformal Verification

Lower-bound residual：

```math
r_i^{lower}
=
\widehat y_i-y_i.
```

Upper-bound residual：

```math
r_i^{upper}
=
y_i-\widehat y_i.
```

有限样本 quantile：

```math
q_{1-\alpha}
=
r_{(\lceil(n+1)(1-\alpha)\rceil)}.
```

形成 one-sided margin，并可对多个约束做 family-wise correction。

---

## 6. Risk-Sensitive Long-Horizon Planning

单步 uplift 最大不代表长期价值最大。候选 sequence 通过 stochastic rollout 估计 return distribution，并使用 downside CVaR：

```math
CVaR_\alpha(R)
=
\mathbb E[R\mid R\le VaR_\alpha(R)].
```

```math
Score(\pi)
=
CVaR_\alpha(R_\pi)
-\lambda\Pr(\mathrm{constraint\ violation}\mid\pi).
```

高均值但 downside tail / violation probability 更差的方案会被降权。

---

## 7. Dynamics-Aware Process Credit

Potential shaping：

```math
F_t
=
\gamma\Phi(s_{t+1})-\Phi(s_t).
```

GAE：

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

只有真实 dynamics discontinuity 才切断 bootstrap / recursive trace。普通 export window 是 truncation metadata，不会仅因切窗改变训练 target。

---

## Real-world benchmark status

### Full Criteo Uplift v2.1 — current locked targeting evidence

当前可审计的 Criteo full-data targeting result 来自预注册 `visit` / top-10% 实验，evidence commit 为 `7ac26a5aebde2c70e1b43264b89f08dddcff0245`。完整证据保存在 [`benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/`](benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/README.md)。

五个候选 `S / T / X / R / DR + LightGBM 4.7.0` 在 50% training split 上固定训练；25% randomized validation 只用于选赢家；只有赢家被允许看到 25% final holdout。`exposure` 是 post-assignment 字段，明确禁止作为 treatment 或 feature。

| Metric | Locked result |
| --- | ---: |
| Source rows | 13,979,592 |
| Training / validation / holdout rows | `6,990,168 / 3,494,354 / 3,495,070` |
| Predeclared CATE candidates | 5 |
| Validation winner | **S-Learner** |
| Validation population increment | `0.0096579179` |
| Final treat-none value | `0.0381058865` |
| Final locked-policy value | `0.0474849889` |
| **Final population incremental visit value** | **`0.0093791024` (+0.93791 pp)** |
| Population 95% CI | **`[0.0089584420, 0.0097997628]`** |
| **Selected top-10% incremental visit value** | **`0.0937910242` (+9.37910 pp)** |
| Selected-group 95% CI | **`[0.0895844204, 0.0979976281]`** |

Validation ranking by population incremental visit value was `S > X > DR > R > T`. S-Learner 是这个**冻结 validation cohort** 上的赢家；这不表示 S-Learner 在其他数据集上普遍优于 DR/R/X。这里遵守的是“locked validation evidence 优先于 estimator novelty”。

`0.0093791024` 是相对 treat-none 的**绝对 population visit-probability 增量**，不是相对百分比；对应约 +0.93791 个百分点。top-10% 的 `0.0937910242` 也是绝对概率增量，对应约 +9.37910 个百分点。locked policy value 相对 treat-none 约高 24.61%，但这个比率与历史 `Uplift@10% +6.8%` 不是同一指标，不能直接比较。

复现该 evidence commit：

```bash
git checkout 7ac26a5aebde2c70e1b43264b89f08dddcff0245
pip install -e '.[criteo]'
python scripts/run_criteo_full_locked.py
```

精确环境以 evidence 目录中的 `environment.txt` 为准。

### Small Open Bandit Dataset

PR CI 使用**真实外部 OBD**，并 pin 到：

```text
sb-ai-lab/sb-obp@1c6d14677ec6f06094a2f8886a1158bab99c571e
```

它运行 2-fold logistic Q、真实 BernoulliTS action distribution、evidence gate、validation selection、single holdout，并上传 plan / manifest / candidate grid / locked result。

这属于 **integration evidence**，不是 full-data headline performance。

### Full Open Bandit Dataset — current locked evidence

当前可审计的 full-data result 来自预注册 `all/random → BernoulliTS` 实验，evidence commit 为 `7d538cea9698b5f0a48c585eed85e3ae526e5af6`。完整证据保存在 [`benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/`](benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/README.md)。

| Metric | Locked result |
| --- | ---: |
| Random-policy evidence rows | 1,374,327 |
| BTS on-policy reference rows | 12,357,200 |
| Predeclared estimator configurations | 9 |
| Validation winner | **IPS** |
| Validation absolute error | `0.0000599942` |
| Final estimate | `0.0045295435` |
| Final on-policy reference | `0.0049885087` |
| **Final relative estimation error** | **9.20045%** |
| Final standard error | `0.0002042614` |
| Validation support / ESS ratio | `1.0 / 0.16144` |
| Final support / ESS ratio | `1.0 / 0.16123` |

IPS 是这个**冻结 validation cohort** 上的赢家，因此只有 IPS 被允许看到 final holdout。它并不推翻 cross-fitted β*-IPS / DR 等 frontier estimators 的方法学价值，也不表示 IPS 在其他数据集上普遍更好；这里遵守的是“validation evidence 优先于 novelty”。

这次 full run 使用 `n_sim=100000`、3-fold logistic Q、support `>= 0.95`、ESS ratio `>= 0.05` 和 positive supported importance mass gates。validation / final support 都为 `1.0`，所有预声明 evidence gates 均通过，且 tuning / test fingerprints 不同。

复现入口：

```bash
pip install -e '.[obd]'
python scripts/run_obd_full_locked.py
```

若已经下载 full OBD：

```bash
python scripts/run_obd_full_locked.py --data-root /path/to/open_bandit_dataset
```

### Historical records

旧的 Criteo `+6.8%` / Open Bandit `-8.4%` 属于 **pre-locked legacy evaluation records**。它们的协议与当前 locked results 不同，因此既不与 Criteo `+0.93791 pp / +9.37910 pp` 直接比较，也不与 OBD `9.20045%` 直接比较，更不用于选择当前 estimator / model。

---

## CI-reproducible algorithmic gates

| Property | Gate |
| --- | ---: |
| GrowthAgentBench CATE RMSE | `< 0.03` |
| Propensity overlap | coverage `> 0.95` |
| Learned CATE policy | oracle regret `< 0.015` |
| Low-support optimistic treatment | cannot increase without support |
| Unsafe expected cost | `NO_TREATMENT` fallback |
| Dynamics boundary | stops GAE leakage |

Synthetic / deterministic regression checks validate implementation semantics; they do not replace real-world evidence。

---

## Implementation map

| Component | Source |
| --- | --- |
| Group-aware Cross-Fitted DR | `growthevo/causal/dr_learner.py` |
| CATE serving bridge | `growthevo/causal/serving.py` |
| Calibrated feasible Safe PI | `growthevo/rl/safe_policy_improvement.py` |
| Cross-fitted β*-IPS + OPE panel | `growthevo/rl/ope.py` |
| Evidence-gated locked OPE | `growthevo/bench/ope_evidence_gate.py` |
| OPE preregistration | `growthevo/bench/ope_experiment_plan.py` |
| Targeting preregistration | `growthevo/bench/targeting_experiment_plan.py` |
| Locked OPE CLI | `growthevo/bench/locked_ope_cli.py` |
| Locked targeting CLI | `growthevo/bench/locked_targeting_cli.py` |
| Full Criteo runner | `scripts/run_criteo_full_locked.py` |
| Full OBD runner | `scripts/run_obd_full_locked.py` |
| One-sided conformal | `growthevo/rl/conformal.py` |
| Risk-sensitive MPC / CVaR | `growthevo/rl/model_based.py` |
| Dynamics-aware GAE | `growthevo/training/trajectory.py` |

算法版本选择：`docs/FRONTIER_ALGORITHM_STACK.md`  
真实数据协议：`docs/REAL_WORLD_BENCHMARKS.md`  
OBD workflow：`docs/OBD_ISOLATED_EXPORT.md`  
Locked OPE schema：`docs/LOCKED_OPE_RUN.md`  
Locked targeting schema：`docs/LOCKED_TARGETING_RUN.md`

---

## Reproduce

Core runtime/tests:

```bash
git clone https://github.com/jiaweine/GrowthEvo-Harness.git
cd GrowthEvo-Harness
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Full Criteo research bridge:

```bash
pip install -e '.[criteo]'
python scripts/run_criteo_full_locked.py
```

Real OBD bridge:

```bash
pip install -e '.[obd]'
```

Full OBD research benchmark:

```bash
python scripts/run_obd_full_locked.py
```

Generated full-data caches and raw score/evidence arrays are gitignored. Compact accepted evidence is persisted under `benchmarks/targeting/results/` and `benchmarks/ope/results/`; archive the final plan, source provenance, manifest, environment and locked artifact, but do not commit the large third-party datasets.

---

## Method boundaries

- Causal estimates are not trusted outside observed support merely because a function approximator can extrapolate.
- Practical overlap, strict positivity and propensity clipping are different concepts.
- Model residual diagnostics are not called causal confidence bounds without an inference/calibration protocol.
- OPE point estimates are insufficient when ESS/support are weak.
- Cross-fitted β*-IPS is the default policy-evidence estimator; validation can still select another predeclared estimator for a benchmark when legitimate reference evidence supports it.
- Policy improvement ranks final feasible pessimistic policies and can consume externally calibrated bounds.
- Long-horizon rollout ranks risk; it does not replace causal estimation.
- `NO_TREATMENT` remains available whenever positive treatment evidence is insufficient.
- Small OBD is integration evidence, not a substitute for the official full research release.
- A changed data source, split, propensity/Q protocol, candidate grid/config or evidence gate is a new experiment plan, not the same benchmark run.

---

<div align="center">

### GrowthEvo-Harness

**Causal estimation · Safe improvement · Counterfactual evaluation · Pre-registered evidence · Risk-sensitive learning**

</div>
