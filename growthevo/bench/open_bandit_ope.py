from __future__ import annotations

from typing import Callable, Hashable, Iterable

from growthevo.rl.ope import LoggedBanditRecord

from .real_world import OpenBanditInteraction


BanditScalarModel = Callable[[OpenBanditInteraction], float]
BanditClusterKey = Callable[[OpenBanditInteraction], Hashable]


def open_bandit_to_ope(
    interactions: Iterable[OpenBanditInteraction],
    *,
    target_action_probability: BanditScalarModel,
    baseline_q: BanditScalarModel,
    target_q: BanditScalarModel,
    cluster_key: BanditClusterKey | None = None,
) -> tuple[LoggedBanditRecord, ...]:
    """Adapt Open Bandit impressions to the generic OPE contract.

    Logged propensities are always preserved. ``cluster_key`` is optional and
    protocol-defined: use it when the evaluation design has a defensible
    independent block such as day, campaign, session, or another collection unit.
    The adapter never guesses that unit from dataset-specific string parsing.
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
                cluster_id=cluster_key(row) if cluster_key is not None else None,
            )
        )
    if not records:
        raise ValueError("at least one Open Bandit interaction is required")
    return tuple(records)
