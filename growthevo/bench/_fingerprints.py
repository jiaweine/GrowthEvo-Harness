"""Stable evidence fingerprints shared by locked benchmark protocols."""

from __future__ import annotations

from hashlib import blake2b
from math import isfinite
from typing import Hashable, Iterable, Mapping, Sequence

from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.rl.ope import LoggedBanditRecord


def hash_lines(lines: Iterable[str]) -> str:
    """Hash a set-like collection of canonical text lines independent of order."""

    digest = blake2b(digest_size=20)
    for line in sorted(lines):
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def stable_hashable(value: Hashable | None) -> str:
    """Encode supported cluster identities without relying on Python's hash seed."""

    if value is None:
        return "none"
    if isinstance(value, bool):
        return f"bool:{int(value)}"
    if isinstance(value, int):
        return f"int:{value}"
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("locked evaluation cluster_id floats must be finite")
        return f"float:{value.hex()}"
    if isinstance(value, str):
        return f"str:{value}"
    if isinstance(value, tuple):
        return "tuple:[" + ",".join(stable_hashable(item) for item in value) + "]"
    raise ValueError(
        "locked evaluation cluster_id must use stable scalar/tuple identity semantics"
    )


def ope_record_ids(rows: Sequence[LoggedBanditRecord]) -> tuple[str, ...]:
    if any(row.record_id is None for row in rows):
        raise ValueError("locked evaluation requires record_id for every OPE record")
    record_ids = tuple(str(row.record_id) for row in rows)
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("locked evaluation requires unique OPE record_id values")
    return record_ids


def ope_records_fingerprint(records: Iterable[LoggedBanditRecord]) -> str:
    """Fingerprint OPE rows including target-policy and Q-model evidence."""

    rows = tuple(records)
    if not rows:
        raise ValueError("at least one OPE record is required")
    ope_record_ids(rows)
    return hash_lines(
        "|".join(
            (
                str(row.record_id),
                float(row.reward).hex(),
                float(row.behavior_propensity).hex(),
                float(row.target_action_probability).hex(),
                float(row.baseline_q).hex(),
                float(row.target_q).hex(),
                stable_hashable(row.cluster_id),
            )
        )
        for row in rows
    )


def treatment_unit_ids(rows: Sequence[LoggedTreatmentRecord]) -> tuple[str, ...]:
    ids = tuple(row.unit_id for row in rows)
    if len(set(ids)) != len(ids):
        raise ValueError("locked evaluation requires unique treatment unit_id values")
    return ids


def treatment_records_fingerprint(records: Iterable[LoggedTreatmentRecord]) -> str:
    """Fingerprint randomized treatment rows independent of source-file order."""

    rows = tuple(records)
    if not rows:
        raise ValueError("at least one treatment record is required")
    treatment_unit_ids(rows)
    return hash_lines(
        "|".join(
            (
                row.unit_id,
                row.action.value,
                float(row.outcome).hex(),
                ",".join(float(value).hex() for value in row.features),
                ",".join(
                    f"{action.value}:{float(probability).hex()}"
                    for action, probability in sorted(
                        row.action_propensities.items(), key=lambda item: item[0].value
                    )
                ),
                "none" if row.group_id is None else f"group:{row.group_id}",
            )
        )
        for row in rows
    )


def targeting_evidence_fingerprint(
    records: Iterable[LoggedTreatmentRecord],
    candidate_scores: Mapping[str, Sequence[float]],
) -> str:
    """Fingerprint randomized rows together with candidate model predictions."""

    rows = tuple(records)
    if not rows:
        raise ValueError("at least one treatment record is required")
    unit_ids = treatment_unit_ids(rows)
    if not candidate_scores:
        raise ValueError("at least one targeting candidate is required")
    lines = [f"data:{treatment_records_fingerprint(rows)}"]
    for candidate_name in sorted(candidate_scores):
        if not candidate_name:
            raise ValueError("targeting candidate names cannot be empty")
        scores = tuple(float(value) for value in candidate_scores[candidate_name])
        if len(scores) != len(rows):
            raise ValueError("candidate scores must align with treatment records")
        if any(not isfinite(score) for score in scores):
            raise ValueError("candidate scores must be finite")
        lines.extend(
            f"score:{candidate_name}|{unit_id}|{score.hex()}"
            for unit_id, score in zip(unit_ids, scores, strict=True)
        )
    return hash_lines(lines)
