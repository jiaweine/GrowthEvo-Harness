"""Deterministic benchmark fixtures for causal growth-policy research."""

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
    "GrowthAgentBench",
    "PolicyBenchmarkResult",
    "SyntheticGrowthSample",
    "evaluate_cate",
    "make_synthetic_growth_bandit",
    "oracle_policy_value",
]
