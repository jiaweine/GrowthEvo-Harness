from __future__ import annotations

from typing import Callable, Hashable, Iterable

from growthevo.rl.ope import LoggedBanditRecord

from .real_world import OpenBanditInteraction


BanditScalarModel = Callable[[OpenBanditInteraction], float]
BanditClusterKey = Callable[[OpenBanditInteraction], Hashable]
BanditRecordIdentity = Callable[[OpenBanditInteraction], str]


def open_bandit_to_ope(
    interactions: Iterable[OpenBanditInteraction],
    *,
    target_action_probability: BanditScalarModel,
    baseline_q: BanditScalarModel,
    target_q: BanditScalarModel,
    cluster_key: BanditClusterKey | None = None,
    record_identity: BanditRecordIdentity | None = None,
) -> tuple[LoggedBanditRecord, ...]:
    """Adapt Open Bandit impressions to the frontier generic OPE contract.

    Logged action propensities are preserved exactly. The caller supplies the
    target-policy action probability and baseline/target Q estimates, so the
    adapter does not smuggle model or policy assumptions into data loading.

    ``cluster_key`` is deliberately protocol-defined. Use it when the experiment
    has a defensible independent block such as day, campaign, session, or another
    collection unit; the adapter never guesses a cluster from a timestamp string.

    ``record_identity`` supplies stable identities for deterministic beta*-IPS
    cross-fitting. If omitted, the OPE layer remains backwards-compatible and
    uses input position. For paper-facing evaluation, provide a source-order-
    invariant identity whenever the dataset protocol can define one.
    """

    records: list[LoggedBanditRecord] = []
    for row in interactions:
        target_probability = float(target_action_probability(row))
        if not 0 <= target_probability <= 1:
            raise ValueError("target policy probability must be in [0, 1]")
        identity = record_identity(row) if record_identity is not None else None
        if identity is not None and not identity:
            raise ValueError("record_identity must return a non-empty string")
        records.append(
            LoggedBanditRecord(
                reward=row.click,
                behavior_propensity=row.propensity_score,
                target_action_probability=target_probability,
                baseline_q=float(baseline_q(row)),
                target_q=float(target_q(row)),
                cluster_id=cluster_key(row) if cluster_key is not None else None,
                record_id=identity,
            )
        )
    if not records:
        raise ValueError("at least one Open Bandit interaction is required")
    return tuple(records)
