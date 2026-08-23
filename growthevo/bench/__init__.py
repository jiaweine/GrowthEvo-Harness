"""Deterministic benchmark fixtures for causal growth-policy research."""

from .synthetic import (
    CATEBenchmarkResult,
    SyntheticGrowthSample,
    evaluate_cate,
    make_synthetic_growth_bandit,
)

__all__ = [
    "CATEBenchmarkResult",
    "SyntheticGrowthSample",
    "evaluate_cate",
    "make_synthetic_growth_bandit",
]
