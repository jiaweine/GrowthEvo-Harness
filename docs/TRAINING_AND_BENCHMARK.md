# Training and Benchmark Contracts

GrowthEvo separates four concerns that are often collapsed into one "RL agent" loop:

1. **causal estimation** — estimate incremental treatment effects from logged data;
2. **policy improvement** — improve only inside supported and constrained action regions;
3. **agent credit assignment** — turn planner/tool trajectories into training samples;
4. **policy promotion** — independently verify a candidate with OPE, calibrated uncertainty and business constraints.

The split is intentional. A training objective is not allowed to redefine the promotion judge.

## 1. Logged treatment contract

`LoggedTreatmentRecord` stores:

```text
unit_id
features
action
outcome
action_propensities[action -> probability]
```

The complete logging-policy probability vector is required for multi-action causal learning. For treatment `a` versus `NO_TREATMENT`, GrowthEvo conditions on the treatment/control pair and renormalizes:

\[
e_a(x)=\frac{\mu(a\mid x)}{\mu(a\mid x)+\mu(a_0\mid x)}.
\]

This avoids applying a binary AIPW formula to an unnormalized multi-arm propensity.

## 2. Cross-Fitted DR-Learner

For each held-out fold, nuisance outcome models are trained without that fold. The held-out doubly-robust pseudo-outcome is:

\[
\tilde\tau_i =
\hat m_1(x_i)-\hat m_0(x_i)
+\frac{A_i(Y_i-\hat m_1(x_i))}{\hat e(x_i)}
-\frac{(1-A_i)(Y_i-\hat m_0(x_i))}{1-\hat e(x_i)}.
\]

The second-stage treatment-effect model is trained only on out-of-fold pseudo-outcomes.

The dependency-free reference backend uses ridge regression so the statistical pipeline is auditable in CI. Production experiments can replace the regression backend without changing the cross-fitting or serving contracts.

### Serving boundary

`CausalUpliftServingBridge` maps fitted treatment-effect models into Runtime uplift beliefs:

```text
channel_effects
channel_uncertainty
channel_support
```

Low support does not become a confident zero. Instead, uncertainty is inflated as support falls. The Runtime can then abstain or choose `NO_TREATMENT`.

The uncertainty value is a serving diagnostic, **not a valid causal confidence interval by itself**.

## 3. Support-Anchored Conservative Policy Improvement

`SupportAnchoredPolicyImprover` computes a pessimistic action value:

\[
LCB(a)=\hat Q(a)-z\,\hat\sigma(a).
\]

Actions below the configured behavior-policy support floor are excluded, except `NO_TREATMENT`, which is always available as the safe fallback.

The candidate policy is a mixture between behavior policy `\mu` and a pessimistically selected supported action `a*`:

\[
\pi_{new}=(1-\eta)\mu+\eta\,\delta_{a^*}.
\]

`η` is bounded by a total-variation update cap and can be reduced further by an expected-cost upper bound. This is a conservative policy-improvement kernel, not a claim that arbitrary upstream uncertainty is statistically calibrated.

Promotion still requires the independent Counterfactual Verifier.

## 4. Planner Trajectory Training

`PlannerTransition` keeps the information needed for external Agent-RL training:

```text
trajectory_id
step_index
action
observation
reward
value_estimate
next_value_estimate
legal_action
tool_success
done
credit_boundary
```

`TrajectoryTrainerAdapter` computes Generalized Advantage Estimation:

\[
\delta_t = r_t + \gamma V(s_{t+1}) - V(s_t),
\]

\[
A_t = \delta_t + \gamma\lambda A_{t+1}.
\]

When `done` or `credit_boundary` is true, bootstrap and advantage propagation stop. A boundary should be used when local credit should not cross:

- rollback / checkpoint restoration;
- environment reset;
- user or segment switch;
- delayed-outcome attribution boundary;
- other known transition-regime changes.

The adapter exports backend-neutral records/JSONL. It intentionally does not pretend to be a full verl, Agent Lightning, PPO or GRPO trainer.

## 5. GrowthAgentBench

`GrowthAgentBench` currently contains an auditable synthetic contextual-bandit fixture with known ground truth.

The generator includes:

- heterogeneous user context;
- context-dependent logging propensities;
- `NO_TREATMENT`, push and email actions;
- known potential-outcome treatment effects;
- configurable outcome noise.

Available held-out metrics include:

- CATE RMSE;
- CATE MAE;
- CATE bias;
- mean support score;
- mean serving uncertainty;
- oracle policy value;
- oracle regret;
- no-treatment rate.

Synthetic benchmark metrics are regression evidence for the implementation, not business results.

## 6. Promotion remains separate

The training stack can propose a better policy, but only the existing evidence chain can promote it:

```text
logged / randomized cohort
    -> OPE (IPS / DR / beta*-IPS)
    -> ESS + support + weight-tail diagnostics
    -> conformal residual calibration when appropriate
    -> Counterfactual Verifier
    -> shadow / canary
    -> promotion or rollback
```

This separation prevents reward hacking through training-time changes to the evaluator.
