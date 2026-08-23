from __future__ import annotations


def test_public_runtime_exports_import_without_cycles() -> None:
    from growthevo.runtime import (
        EventStore,
        GrowthEvoRuntime,
        GrowthHypothesisPlanner,
        LegalActionGate,
    )

    assert EventStore is not None
    assert GrowthEvoRuntime is not None
    assert GrowthHypothesisPlanner is not None
    assert LegalActionGate is not None


def test_evolution_submodule_imports_without_runtime_cycle() -> None:
    from growthevo.evolution.optimizer import HarnessEvolver

    assert HarnessEvolver is not None


def test_frontier_rl_exports_import_without_cycles() -> None:
    from growthevo.rl import (
        ConformalPolicyCalibrator,
        GrowthProcessRewardModel,
        RiskSensitiveMPC,
        evaluate_policy,
        policy_evidence_from_ope,
    )

    assert ConformalPolicyCalibrator is not None
    assert GrowthProcessRewardModel is not None
    assert RiskSensitiveMPC is not None
    assert evaluate_policy is not None
    assert policy_evidence_from_ope is not None
