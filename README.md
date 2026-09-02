<div align="center">

# GrowthEvo-Harness

### Causal Reinforcement Learning for Incremental User Growth

**Optimize the incremental value created by an action, with support-aware policy learning and locked real-world evidence.**

[![CI](https://github.com/jiaweine/GrowthEvo-Harness/actions/workflows/ci.yml/badge.svg)](https://github.com/jiaweine/GrowthEvo-Harness/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
![Version](https://img.shields.io/badge/version-0.1.0-111827)
![Causal RL](https://img.shields.io/badge/Causal-Reinforcement%20Learning-7C3AED)
![OPE](https://img.shields.io/badge/OPE-Cross--Fitted%20%CE%B2*--IPS%20%7C%20DR-0891B2)
![Evidence](https://img.shields.io/badge/Evidence-Pre--Registered%20%7C%20Locked-059669)

`Cross-Fitted DR` · `Safe Policy Improvement` · `Robust OPE` · `Locked Evaluation` · `Conformal Verification` · `Risk-Sensitive Planning`

<br>

[Overview](#overview) · [Highlights](#highlights) · [Locked Evidence](#locked-real-world-evidence) · [Capabilities](#capability-matrix) · [Quick Start](#quick-start) · [Architecture](#architecture) · [Docs](#documentation)

</div>

---

## Overview

GrowthEvo-Harness 是一个面向 **增量增长决策（incremental growth decision-making）** 的因果强化学习研究框架。

传统 propensity / conversion model 更关注“谁更可能转化”；GrowthEvo 直接建模和评估 **某个动作相对 `NO_TREATMENT` 实际带来的增量价值**，并把数据支持度、安全约束、反事实评估与可审计实验协议统一到同一套 harness 中。

核心对象是 conditional treatment effect：

```math
\tau(x,a)
=
\mathbb{E}[Y(a)-Y(a_0)\mid X=x],
\qquad a_0=\mathrm{NO\_TREATMENT}.
```

`NO_TREATMENT` 在 GrowthEvo 中是一级动作。策略优化以因果增量、可执行性和证据质量为共同约束，而不是只对 raw prediction score 做排序。

<table>
<tr>
<td width="25%" valign="top"><b>Incrementality First</b><br><sub>直接优化 treatment effect 与 incremental value。</sub></td>
<td width="25%" valign="top"><b>Support Aware</b><br><sub>把 overlap、positivity 与 distributional support 纳入决策。</sub></td>
<td width="25%" valign="top"><b>Safe Improvement</b><br><sub>在 trust region、成本上界与保守价值下优化最终可执行策略。</sub></td>
<td width="25%" valign="top"><b>Locked Evidence</b><br><sub>预注册候选、冻结验证选择，并使用独立 final holdout。</sub></td>
</tr>
</table>

---

## Highlights

### A unified causal decision harness

GrowthEvo 将因果估计、策略改进、OPE、实验锁定、长期风险和轨迹 credit 组织成一套可组合研究栈：

| Area | GrowthEvo capability |
| --- | --- |
| **Causal effect estimation** | Group-aware cross-fitted Doubly Robust CATE，支持可替换 nuisance / effect learners |
| **Support modeling** | Strict positivity、practical overlap、propensity handling、distributional support |
| **Safe policy improvement** | Calibrated pessimistic value、conservative cost、TV trust region、final-feasible ranking |
| **Off-policy evaluation** | Cross-fitted β*-IPS、DM、IPS、SNIPS、DR、SWITCH-DR、DR-OS、Meta-OPE |
| **Evidence protocol** | Pre-registered plans、realized manifests、evidence gates、frozen validation winner、final holdout |
| **Verification** | One-sided conformal margins 与多约束 family-wise correction |
| **Long-horizon planning** | Stochastic rollout、downside CVaR、constraint-aware model-based planning |
| **Trajectory learning** | Potential shaping、GAE、dynamics-aware bootstrap boundaries |

### Research principles

- **Incrementality before ranking**：优先比较可归因增量，而不是 raw conversion probability。
- **Support-aware optimization**：让可观测数据支持度参与动作选择和策略改进。
- **Calibration-aware confidence**：置信边界来自明确的校准或推断协议。
- **Feasibility-aware selection**：直接比较满足约束后的 final-feasible policies。
- **Validation-governed model selection**：候选方法在预声明 validation 上竞争，赢家冻结后进入 final holdout。
- **Artifact-backed evidence**：实验计划、数据清单、候选配置、环境和结果通过 fingerprint chain 绑定。

---

## Locked real-world evidence

GrowthEvo 的 headline benchmark 使用预注册实验计划、独立 validation selection 和冻结 final holdout。完整结果与 provenance artifact 均保存在仓库中。

### Criteo Uplift v2.1 · locked targeting

预注册 `visit` / top-10% targeting 实验使用 **13,979,592** 条源数据。五个固定的 LightGBM 4.7.0 CATE candidates 在 training split 上训练，并在 randomized validation 上完成冻结选择。

| Metric | Locked result |
| --- | ---: |
| Source rows | **13,979,592** |
| Training / validation / holdout | `6,990,168 / 3,494,354 / 3,495,070` |
| Predeclared CATE candidates | **5** |
| Validation winner | **S-Learner** |
| Final locked-policy value | **0.0474849889** |
| Treat-none value | `0.0381058865` |
| Population incremental visit | **+0.93791 pp** |
| Population 95% CI | **[+0.89584 pp, +0.97998 pp]** |
| Selected top-10% incremental visit | **+9.37910 pp** |
| Selected-group 95% CI | **[+8.95844 pp, +9.79976 pp]** |

**Evidence commit:** `7ac26a5aebde2c70e1b43264b89f08dddcff0245`

[View the complete Criteo evidence bundle](benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/README.md)

### Open Bandit Dataset · locked OPE

Full OBD benchmark evaluates a BernoulliTS target policy from randomized logged data with a predeclared estimator grid, 3-fold logistic Q model, evidence gates and an independent final holdout.

| Metric | Locked result |
| --- | ---: |
| Random-policy evidence rows | **1,374,327** |
| BernoulliTS on-policy reference rows | **12,357,200** |
| Predeclared estimator configurations | **9** |
| Validation winner | **IPS** |
| Final estimate | **0.0045295435** |
| Final standard error | `0.0002042614` |
| Final support coverage | **1.0000** |
| Final ESS ratio | **0.16123** |

**Evidence commit:** `7d538cea9698b5f0a48c585eed85e3ae526e5af6`

[View the complete OBD evidence bundle](benchmarks/ope/results/obd-full-all-random-to-bts/7d538cea/README.md)

---

## Capability matrix

### 1. Group-Aware Cross-Fitted DR CATE

GrowthEvo 使用 held-out folds 构造 doubly-robust pseudo-outcomes，并支持 repeated users / clusters 的 group-aware fold assignment。

对于 treatment `a` 和 control `a₀`，multi-action logging propensity 在 pair 内归一化：

```math
e_a(x)
=
\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
```

DR pseudo-outcome：

```math
\widetilde\tau_i
=
\widehat m_1(x_i)-\widehat m_0(x_i)
+
\frac{A_i(Y_i-\widehat m_1(x_i))}{\widehat e(x_i)}
-
\frac{(1-A_i)(Y_i-\widehat m_0(x_i))}{1-\widehat e(x_i)}.
```

同时提供 OOF uncertainty diagnostic 与 regularized Mahalanobis distributional support，用于识别训练分布中的有效覆盖区域。

### 2. Calibrated Safe Policy Improvement

Safe PI 直接消费上游校准 / 推断得到的 pessimistic value 与 conservative cost：

```math
Q_a^- = L_a,
\qquad
C_a^+ = U_a.
```

策略改进在 behavior policy 周围执行，并同时考虑：

- TV trust region；
- conservative cost limit；
- support-aware action feasibility；
- `NO_TREATMENT` fallback；
- final-feasible pessimistic policy value。

这使策略选择直接发生在“可执行策略空间”中，而不是对未经约束的动作分数做后处理。

### 3. Robust Off-Policy Evaluation

GrowthEvo 默认提供 **cross-fitted β*-IPS**，并同时暴露一组 OPE estimators 供预注册 benchmark selection 与 robustness analysis 使用。

Importance weight：

```math
w_i
=
\frac{\pi(a_i\mid x_i)}{\mu(a_i\mid x_i)}.
```

Doubly Robust：

```math
\widehat V_{DR}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
\widehat q_\pi(x_i)
+w_i(r_i-\widehat q(x_i,a_i))
\right].
```

Cross-fitted β*-IPS：

```math
\widehat V_{\beta,CF}
=
\frac{1}{n}\sum_{i=1}^{n}
\left[
w_i r_i
-\widehat\beta^*_{-f(i)}(w_i-1)
\right].
```

OPE artifact 同时记录 estimator-specific SE、ESS、ESS ratio、support coverage、maximum importance weight、normalization diagnostics 与可选 cluster-robust statistics。

### 4. Pre-Registered Locked Evaluation

GrowthEvo 使用显式 experiment plan 固定实验定义，并将 validation selection 与 final holdout 分开。

**OPEExperimentPlan** 可以锁定：

- dataset source 与 policy direction；
- reward definition 与 split；
- Q model / folds；
- target-policy Monte Carlo count；
- support floor 与 evidence gates；
- estimator / hyperparameter grid；
- random seed 与 artifact fingerprints。

**TargetingExperimentPlan** 可以锁定：

- dataset source 与 outcome；
- train / validation / holdout split；
- treatment 与 selected fraction；
- propensity protocol；
- score-generation protocol；
- complete candidate set；
- candidate-config fingerprint。

最终 evidence bundle 绑定 experiment plan、candidate config、realized export manifest、validation evidence、holdout evidence、环境信息与 code commit SHA。

### 5. One-Sided Conformal Verification

对 lower / upper residual 分别校准 one-sided quantile：

```math
q_{1-\alpha}
=
r_{(\lceil(n+1)(1-\alpha)\rceil)}.
```

可生成 conservative margins，并支持多约束 family-wise correction，便于将预测不确定性接入策略约束。

### 6. Risk-Sensitive Long-Horizon Planning

候选 action sequence 通过 stochastic rollout 估计 return distribution，并用 downside CVaR 与 violation probability 进行风险敏感排序：

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

### 7. Dynamics-Aware Process Credit

GrowthEvo 提供 potential shaping 与 GAE，并依据真实 dynamics boundary 控制 bootstrap 与 recursive trace。

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

---

## Quick start

### Install for development

```bash
git clone https://github.com/jiaweine/GrowthEvo-Harness.git
cd GrowthEvo-Harness

python -m venv .venv
source .venv/bin/activate

pip install -e '.[dev]'
pytest
```

Python requirement: **3.11+**.

### Optional benchmark dependencies

Criteo benchmark stack:

```bash
pip install -e '.[criteo]'
```

Open Bandit Dataset stack:

```bash
pip install -e '.[obd]'
```

### CLI entry points

```bash
growthevo-locked-ope --help
growthevo-locked-targeting --help
```

---

## Reproduce locked benchmarks

### Full Criteo targeting

```bash
git checkout 7ac26a5aebde2c70e1b43264b89f08dddcff0245
pip install -e '.[criteo]'
python scripts/run_criteo_full_locked.py
```

对应 evidence 环境保存在：

```text
benchmarks/targeting/results/criteo-v2.1-visit-top10/7ac26a5a/environment.txt
```

### Full Open Bandit Dataset OPE

```bash
pip install -e '.[obd]'
python scripts/run_obd_full_locked.py
```

如果本地已经准备好 full OBD：

```bash
python scripts/run_obd_full_locked.py --data-root /path/to/open_bandit_dataset
```

---

## Architecture

GrowthEvo 的实现按 causal estimation、policy learning、evaluation、benchmark governance 和 trajectory learning 分层组织。

| Layer | Main modules | Responsibility |
| --- | --- | --- |
| **Causal** | `growthevo/causal/dr_learner.py` | Group-aware cross-fitted DR CATE |
| **Serving** | `growthevo/causal/serving.py` | CATE serving bridge |
| **Policy** | `growthevo/rl/safe_policy_improvement.py` | Calibrated final-feasible Safe PI |
| **OPE** | `growthevo/rl/ope.py` | β*-IPS and robust estimator panel |
| **Verification** | `growthevo/rl/conformal.py` | One-sided conformal calibration |
| **Planning** | `growthevo/rl/model_based.py` | Risk-sensitive MPC / CVaR |
| **Trajectory** | `growthevo/training/trajectory.py` | Dynamics-aware GAE and shaping |
| **Evidence gates** | `growthevo/bench/ope_evidence_gate.py` | Support and evidence eligibility |
| **Experiment plans** | `growthevo/bench/*experiment_plan.py` | Pre-registration schemas and fingerprints |
| **Locked CLIs** | `growthevo/bench/locked_*_cli.py` | Validation selection and final holdout execution |
| **Benchmark runners** | `scripts/run_*_full_locked.py` | Full-data research benchmark entry points |

### Repository layout

```text
GrowthEvo-Harness/
├── growthevo/
│   ├── causal/
│   ├── rl/
│   ├── bench/
│   └── training/
├── benchmarks/
│   ├── targeting/
│   └── ope/
├── docs/
├── examples/
├── scripts/
├── tests/
├── pyproject.toml
└── README.md
```

---

## Evidence & reproducibility

GrowthEvo 将 benchmark evidence 当作一等 artifact 管理。

每个 locked experiment 可以携带：

- experiment-plan fingerprint；
- candidate-config fingerprint；
- realized export-manifest fingerprint；
- validation / holdout fingerprints；
- source provenance；
- environment snapshot；
- code commit SHA；
- compact accepted evidence bundle。

大型第三方数据与生成缓存不进入 git；可审计的 compact evidence 持久化在：

```text
benchmarks/targeting/results/
benchmarks/ope/results/
```

---

## Documentation

| Topic | Document |
| --- | --- |
| Frontier algorithm stack | [`docs/FRONTIER_ALGORITHM_STACK.md`](docs/FRONTIER_ALGORITHM_STACK.md) |
| Real-world benchmark protocol | [`docs/REAL_WORLD_BENCHMARKS.md`](docs/REAL_WORLD_BENCHMARKS.md) |
| OBD isolated export workflow | [`docs/OBD_ISOLATED_EXPORT.md`](docs/OBD_ISOLATED_EXPORT.md) |
| Locked OPE schema | [`docs/LOCKED_OPE_RUN.md`](docs/LOCKED_OPE_RUN.md) |
| Locked targeting schema | [`docs/LOCKED_TARGETING_RUN.md`](docs/LOCKED_TARGETING_RUN.md) |
| Changelog | [`CHANGELOG.md`](CHANGELOG.md) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| Security | [`SECURITY.md`](SECURITY.md) |

---

## Citation

如果 GrowthEvo-Harness 对你的研究或实验有帮助，可以使用仓库中的 [`CITATION.cff`](CITATION.cff) 获取 citation metadata。

---

<div align="center">

### GrowthEvo-Harness

**Causal estimation · Safe improvement · Counterfactual evaluation · Locked evidence · Risk-sensitive learning**

<sub>Built for auditable incremental decision research.</sub>

</div>
