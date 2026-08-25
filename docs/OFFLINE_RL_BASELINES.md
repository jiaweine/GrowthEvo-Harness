# Offline RL Baseline Contract

The sequential benchmark should compare GrowthEvo against established offline-RL and sequence-modeling methods without changing the meaning of the logged data to make an algorithm easier to run.

## Why KuaiRand needs an action encoder

KuaiRand is a recommendation dataset with a very large video catalog. Treating every `video_id` as an unrelated one-hot action creates an enormous discrete action head and is not a fair default implementation for CQL, IQL, or a sequence model.

`kuairand_to_offline_rl()` therefore exports both:

```text
action_id
optional action_features
```

The exact item id is retained for auditability. `action_features` can contain official item metadata or a precomputed embedding. User features can likewise be injected into state with `user_feature_lookup`.

The official feature loaders support filtering by ids observed in the experiment split, which avoids materializing unrelated catalog entries:

```python
user_features = load_kuairand_user_features(
    "user_features.csv",
    user_ids={row.user_id for row in interactions},
)
video_features = load_kuairand_video_features(
    "video_features_basic.csv",
    video_ids={row.video_id for row in interactions},
)

dataset = kuairand_to_offline_rl(
    interactions,
    user_feature_lookup=user_features,
    action_feature_lookup=video_features,
)
```

Categorical fields remain categorical. Do not assign arbitrary ordinal numbers to values such as activity bands or upload types unless the encoder explicitly models that choice.

## State construction

For transition `t`, the policy state contains only information available before observing feedback from the current recommended video:

```text
user id / allowed static user features
date and clock context
surface/tab
history length
prior mean reward
prior click rate
prior long-view rate
```

Current click/like/follow/comment/forward/hate/long-view signals are reward-side information and enter history only in `next_state`.

The `is_rand` field is stored as `random_intervention` metadata and is not part of the offline-RL policy state. It identifies the historical logging mechanism; treating it as a deployment feature would let a learned policy condition on information that is not a normal user/environment state.

Artificial trajectory chunk boundaries are terminal for bootstrapping. This keeps CQL/IQL temporal-difference targets and sequence windows from crossing a boundary introduced by batching.

## Baselines

### Behavior Cloning

Behavior Cloning is mandatory. If an offline-RL method does not beat a strong behavior-cloning model under a defensible evaluator, the additional value-learning machinery has not demonstrated value.

Recommended action representation:

```text
state encoder + item/action encoder -> compatibility score
```

Report top-k action agreement or ranking quality separately from policy-value claims.

### Conservative Q-Learning

Reference: Kumar et al., *Conservative Q-Learning for Offline Reinforcement Learning*, NeurIPS 2020.

Use a representation-based critic for the recommendation action space:

```text
Q(state_embedding, action_embedding)
```

The conservative penalty should be evaluated over a documented candidate-action sampler rather than over an implicit "all videos" action set. Candidate construction is part of the experimental protocol and must be held constant across methods.

### Implicit Q-Learning

Reference: Kostrikov, Nair, Levine, *Offline Reinforcement Learning with Implicit Q-Learning*, ICLR 2022.

IQL is useful because policy extraction does not require querying arbitrary unseen actions during value fitting. For recommendation, the actor still needs a candidate set or action encoder at inference time. Keep the same candidate generator used for CQL.

### Decision Transformer

Reference: Chen et al., *Decision Transformer: Reinforcement Learning via Sequence Modeling*, NeurIPS 2021.

Use trajectory windows containing:

```text
return-to-go
state representation
action representation
```

Do not compute return-to-go across artificial chunk boundaries. Report context length and reward scaling explicitly.

### Multi-task Offline RL for advertising

Reference: Liu et al., *Multi-task Offline Reinforcement Learning for Online Advertising in Recommender Systems*, KDD 2025.

This method is especially relevant to GrowthEvo because it combines causal state representation, temporal modeling, multiple decision tasks, and advertising constraints. A fair comparison should reproduce only the components supported by the public data. KuaiRand can exercise sequential state/feedback modeling; Criteo can exercise randomized advertising incrementality. Public datasets do not automatically reproduce a proprietary channel-and-budget environment.

## Candidate-action protocol

Large-catalog offline RL is extremely sensitive to candidate generation. Fix the candidate set before comparing algorithms.

A defensible public-data protocol is:

1. Include the logged action.
2. Add items sampled from the same documented candidate pool or from a fixed popularity/semantic retriever trained only on training data.
3. Never sample candidates using future clicks or test-period popularity.
4. Use the identical candidate sets for Behavior Cloning, CQL, IQL, and Decision Transformer evaluation.
5. Report candidate recall of the logged positive action so failures in retrieval are not misattributed to RL.

## Evaluation limits

KuaiRand's `is_rand` flag is not an action propensity. GrowthEvo does not manufacture IPS weights from it.

Therefore, a paper should separate:

- **training comparison**: BC/CQL/IQL/Decision Transformer on the same sequential data and action representations;
- **logged-action predictive metrics**: useful diagnostics, but not counterfactual policy value;
- **random-intervention analyses**: useful for reducing recommendation-policy confounding, but still subject to the exact intervention design;
- **policy-value claims**: require a justified evaluator such as a separately validated response/world model, known propensities, or an online/randomized experiment.

If a learned world model is used, report its held-out error on random-intervention data and sensitivity of policy rankings to model uncertainty. Do not label model-predicted return as observed business lift.

## Recommended experiment grid

```text
Method
  Behavior Cloning
  CQL
  IQL
  Decision Transformer
  GrowthEvo policy

State
  short history
  long history
  + official user features

Action representation
  id embedding
  + official video features

Reward
  click only
  multi-feedback reward
  multi-feedback reward with hate penalty

Safety / support
  no support guard
  support-anchored candidate restriction
```

Run multiple seeds for learned models and report mean, dispersion, and the exact data split. Hyperparameters must be selected on validation data, not the final test comparison.
