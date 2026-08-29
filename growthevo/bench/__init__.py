"""Benchmark fixtures and real-world dataset adapters for growth-policy research."""

from .criteo import CriteoUpliftData, load_criteo_uplift
from .kuairand_features import load_kuairand_user_features, load_kuairand_video_features
from .locked_evaluation import (
    LockedBenchmarkArtifact,
    LockedOPEProtocol,
    LockedTargetingProtocol,
    OPECandidate,
    OPEHoldoutResult,
    OPEValidationScore,
    TargetingHoldoutResult,
    TargetingValidationScore,
    ope_records_fingerprint,
    targeting_evidence_fingerprint,
    treatment_records_fingerprint,
)
from .offline_rl import (
    HistorySummary,
    OfflineRLDataset,
    OfflineRLTransition,
    default_kuairand_state_builder,
    kuairand_to_offline_rl,
)
from .open_bandit_features import load_open_bandit_item_context
from .open_bandit_ope import open_bandit_to_ope
from .planner_sequences import (
    KuaiRandHistory,
    KuaiRandPlannerRecord,
    default_planner_observation,
    kuairand_to_planner_records,
    kuairand_to_planner_transitions,
)
from .real_world import (
    DEFAULT_KUAIRAND_REWARD_WEIGHTS,
    KuaiRandInteraction,
    OpenBanditInteraction,
    RandomizedTargetingResult,
    evaluate_randomized_targeting,
    kuairand_reward,
    load_kuairand,
    load_open_bandit,
)
from .runner import GrowthAgentBench, PolicyBenchmarkResult
from .splits import DatasetSplit, deterministic_stratified_split, ordered_split
from .statistics import TargetingBootstrapResult, bootstrap_randomized_targeting
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
    "DatasetSplit",
    "GrowthAgentBench",
    "HistorySummary",
    "KuaiRandHistory",
    "KuaiRandInteraction",
    "KuaiRandPlannerRecord",
    "LockedBenchmarkArtifact",
    "LockedOPEProtocol",
    "LockedTargetingProtocol",
    "OPECandidate",
    "OPEHoldoutResult",
    "OPEValidationScore",
    "OfflineRLDataset",
    "OfflineRLTransition",
    "OpenBanditInteraction",
    "PolicyBenchmarkResult",
    "RandomizedTargetingResult",
    "SyntheticGrowthSample",
    "TargetingBootstrapResult",
    "TargetingHoldoutResult",
    "TargetingValidationScore",
    "bootstrap_randomized_targeting",
    "default_kuairand_state_builder",
    "default_planner_observation",
    "deterministic_stratified_split",
    "evaluate_cate",
    "evaluate_randomized_targeting",
    "kuairand_reward",
    "kuairand_to_offline_rl",
    "kuairand_to_planner_records",
    "kuairand_to_planner_transitions",
    "load_criteo_uplift",
    "load_kuairand",
    "load_kuairand_user_features",
    "load_kuairand_video_features",
    "load_open_bandit",
    "load_open_bandit_item_context",
    "make_synthetic_growth_bandit",
    "ope_records_fingerprint",
    "open_bandit_to_ope",
    "oracle_policy_value",
    "ordered_split",
    "targeting_evidence_fingerprint",
    "treatment_records_fingerprint",
]
