"""Benchmark fixtures and real-world dataset adapters for growth-policy research."""

from .kuairand_features import load_kuairand_user_features, load_kuairand_video_features
from .offline_rl import OfflineRLDataset, OfflineRLTransition, kuairand_to_offline_rl
from .real_world import (
    CriteoUpliftData,
    DEFAULT_KUAIRAND_REWARD_WEIGHTS,
    KuaiRandInteraction,
    OpenBanditInteraction,
    RandomizedTargetingResult,
    evaluate_randomized_targeting,
    kuairand_reward,
    kuairand_to_planner_transitions,
    load_criteo_uplift,
    load_kuairand,
    load_open_bandit,
    open_bandit_to_ope,
)
from .runner import GrowthAgentBench, PolicyBenchmarkResult
from .synthetic import (
    CATEBenchmarkResult,
    SyntheticGrowthSample,
    evaluate_cate,
    make_synthetic_growth_bandit,
    oracle_policy_value,
)

__all__ = [
    "CATEBenchmarkResult",
    "CriteoUpliftData",
    "DEFAULT_KUAIRAND_REWARD_WEIGHTS",
    "GrowthAgentBench",
    "KuaiRandInteraction",
    "OfflineRLDataset",
    "OfflineRLTransition",
    "OpenBanditInteraction",
    "PolicyBenchmarkResult",
    "RandomizedTargetingResult",
    "SyntheticGrowthSample",
    "evaluate_cate",
    "evaluate_randomized_targeting",
    "kuairand_reward",
    "kuairand_to_offline_rl",
    "kuairand_to_planner_transitions",
    "load_criteo_uplift",
    "load_kuairand",
    "load_kuairand_user_features",
    "load_kuairand_video_features",
    "load_open_bandit",
    "make_synthetic_growth_bandit",
    "open_bandit_to_ope",
    "oracle_policy_value",
]
