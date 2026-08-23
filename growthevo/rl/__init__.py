"""RL package with lazy exports so training backends can evolve independently."""

from __future__ import annotations

from typing import Any

__all__ = [
    "CausalRewardModel",
    "CandidateRolloutScore",
    "ConformalCalibrationRecord",
    "ConformalMargins",
    "ConformalPolicyCalibrator",
    "GrowthProcessRewardModel",
    "HierarchicalGrowthPolicy",
    "LoggedBanditRecord",
    "OPEEstimate",
    "PolicyConfig",
    "ProcessState",
    "RewardWeights",
    "RiskSensitiveMPC",
    "StressScenario",
    "TrajectoryStepSignal",
    "evaluate_policy",
    "policy_evidence_from_ope",
]


def __getattr__(name: str) -> Any:
    if name in {"CausalRewardModel", "RewardWeights"}:
        from .causal_reward import CausalRewardModel, RewardWeights

        return {"CausalRewardModel": CausalRewardModel, "RewardWeights": RewardWeights}[name]
    if name in {"HierarchicalGrowthPolicy", "PolicyConfig"}:
        from .hierarchical_policy import HierarchicalGrowthPolicy, PolicyConfig

        return {
            "HierarchicalGrowthPolicy": HierarchicalGrowthPolicy,
            "PolicyConfig": PolicyConfig,
        }[name]
    if name in {"LoggedBanditRecord", "OPEEstimate", "evaluate_policy", "policy_evidence_from_ope"}:
        from .ope import LoggedBanditRecord, OPEEstimate, evaluate_policy, policy_evidence_from_ope

        return {
            "LoggedBanditRecord": LoggedBanditRecord,
            "OPEEstimate": OPEEstimate,
            "evaluate_policy": evaluate_policy,
            "policy_evidence_from_ope": policy_evidence_from_ope,
        }[name]
    if name in {"ConformalCalibrationRecord", "ConformalMargins", "ConformalPolicyCalibrator"}:
        from .conformal import ConformalCalibrationRecord, ConformalMargins, ConformalPolicyCalibrator

        return {
            "ConformalCalibrationRecord": ConformalCalibrationRecord,
            "ConformalMargins": ConformalMargins,
            "ConformalPolicyCalibrator": ConformalPolicyCalibrator,
        }[name]
    if name in {"GrowthProcessRewardModel", "ProcessState", "TrajectoryStepSignal"}:
        from .process_reward import GrowthProcessRewardModel, ProcessState, TrajectoryStepSignal

        return {
            "GrowthProcessRewardModel": GrowthProcessRewardModel,
            "ProcessState": ProcessState,
            "TrajectoryStepSignal": TrajectoryStepSignal,
        }[name]
    if name in {"CandidateRolloutScore", "RiskSensitiveMPC", "StressScenario"}:
        from .model_based import CandidateRolloutScore, RiskSensitiveMPC, StressScenario

        return {
            "CandidateRolloutScore": CandidateRolloutScore,
            "RiskSensitiveMPC": RiskSensitiveMPC,
            "StressScenario": StressScenario,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
