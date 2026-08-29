from __future__ import annotations

from typing import Callable, Iterable

from growthevo.rl.ope import LoggedBanditRecord

from .real_world import OpenBanditInteraction


BanditScalarModel = Callable[[OpenBanditInteraction], float]


def open_bandit_to_ope(
    interactions: Iterable[OpenBanditInteraction],
    *,
    target_action_probability: BanditScalarModel,
    baseline_q: BanditScalarModel,
    target_q: BanditScalarModel,
) -> tuple[LoggedBanditRecord, ...]:
    """Adapt Open Bandit impressions to the current generic OPE contract.

    Logged action propensities are preserved exactly. The caller supplies the
    target-policy action probability and the baseline/target Q estimates so the
    adapter does not smuggle model or policy assumptions into data loading.
    """

    records: list[LoggedBanditRecord] = []
    for row in interactions:
        target_probability = float(target_action_probability(row))
        if not 0 <= target_probability <= 1:
            raise ValueError("target policy probability must be in [0, 1]")
        records.append(
            LoggedBanditRecord(
                reward=row.click,
                behavior_propensity=row.propensity_score,
                target_action_probability=target_probability,
                baseline_q=float(baseline_q(row)),
                target_q=float(target_q(row)),
            )
        )
    if not records:
        raise ValueError("at least one Open Bandit interaction is required")
    return tuple(records)
