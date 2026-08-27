from __future__ import annotations

import csv
from dataclasses import dataclass
from gzip import open as gzip_open
from math import fsum
from pathlib import Path
from typing import Iterable, Mapping, TextIO

from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel


PathLike = str | Path


def _open_csv(path: PathLike) -> TextIO:
    resolved = Path(path)
    if resolved.suffix == ".gz":
        return gzip_open(resolved, mode="rt", encoding="utf-8", newline="")
    return resolved.open(mode="r", encoding="utf-8", newline="")


def _read_float(row: Mapping[str, str], key: str) -> float:
    try:
        return float(row[key])
    except KeyError as exc:
        raise ValueError(f"missing required column: {key}") from exc
    except (TypeError, ValueError) as exc:
        raise ValueError(f"column {key!r} must be numeric") from exc


def _read_int(row: Mapping[str, str], key: str) -> int:
    value = _read_float(row, key)
    integer = int(value)
    if value != integer:
        raise ValueError(f"column {key!r} must be integer-valued")
    return integer


def _read_binary(row: Mapping[str, str], key: str) -> float:
    value = _read_float(row, key)
    if value not in {0.0, 1.0}:
        raise ValueError(f"column {key!r} must be binary")
    return value


@dataclass(frozen=True, slots=True)
class RandomizedTargetingResult:
    sample_size: int
    selected_fraction: float
    policy_value: float
    treat_none_value: float
    treat_all_value: float
    incremental_value_vs_none: float


def evaluate_randomized_targeting(
    records: Iterable[LoggedTreatmentRecord],
    scores: Iterable[float],
    *,
    selected_fraction: float,
    treatment: Channel = Channel.ADS,
) -> RandomizedTargetingResult:
    """Evaluate a top-score treatment policy with randomized inverse weighting.

    This metric evaluates the actual targeting decision instead of treating
    response prediction as uplift. It is appropriate only when the source cohort
    was randomized and the assignment probabilities in ``records`` are trusted.
    """

    if not 0 < selected_fraction <= 1:
        raise ValueError("selected_fraction must be in (0, 1]")
    rows = list(records)
    rank_scores = [float(score) for score in scores]
    if not rows or len(rows) != len(rank_scores):
        raise ValueError("records and scores must be non-empty and aligned")

    ranked = sorted(range(len(rows)), key=lambda index: (-rank_scores[index], index))
    selected_count = max(1, int(round(len(rows) * selected_fraction)))
    selected = set(ranked[:selected_count])

    policy_terms: list[float] = []
    none_terms: list[float] = []
    all_terms: list[float] = []
    for index, row in enumerate(rows):
        desired = treatment if index in selected else Channel.NO_TREATMENT
        if desired in row.action_propensities and row.action is desired:
            policy_terms.append(row.outcome / row.action_propensities[desired])
        else:
            policy_terms.append(0.0)
        if row.action is Channel.NO_TREATMENT:
            none_terms.append(row.outcome / row.action_propensities[Channel.NO_TREATMENT])
        else:
            none_terms.append(0.0)
        if row.action is treatment:
            all_terms.append(row.outcome / row.action_propensities[treatment])
        else:
            all_terms.append(0.0)

    n = len(rows)
    policy_value = fsum(policy_terms) / n
    treat_none_value = fsum(none_terms) / n
    treat_all_value = fsum(all_terms) / n
    return RandomizedTargetingResult(
        sample_size=n,
        selected_fraction=selected_count / n,
        policy_value=policy_value,
        treat_none_value=treat_none_value,
        treat_all_value=treat_all_value,
        incremental_value_vs_none=policy_value - treat_none_value,
    )


@dataclass(frozen=True, slots=True)
class OpenBanditInteraction:
    timestamp: str
    item_id: int
    position: int
    click: float
    propensity_score: float
    context: tuple[float, ...]
    categorical_context: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.timestamp:
            raise ValueError("timestamp cannot be empty")
        if self.position < 0:
            raise ValueError("position must be non-negative")
        if self.click not in {0.0, 1.0}:
            raise ValueError("click must be binary")
        if not 0 < self.propensity_score <= 1:
            raise ValueError("propensity_score must be in (0, 1]")


def _open_bandit_context_columns(
    fieldnames: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    names = list(fieldnames)
    numeric = tuple(
        name
        for name in names
        if name.startswith(("user-item_affinity", "user_item_affinity"))
    )
    categorical = tuple(name for name in names if name.startswith("user_feature"))
    return numeric, categorical


def load_open_bandit(
    path: PathLike,
    *,
    max_rows: int | None = None,
) -> tuple[OpenBanditInteraction, ...]:
    """Load Open Bandit impressions while preserving logged propensities.

    Current public files use ``propensity_score``. Older official sample files
    used ``action_prob`` for the logged action probability. Categorical user
    features are preserved as strings rather than coerced into arbitrary ordinal
    numbers; item context is loaded separately by ``open_bandit_features``.
    """

    if max_rows is not None and max_rows <= 0:
        raise ValueError("max_rows must be positive when provided")
    interactions: list[OpenBanditInteraction] = []
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        required = {"timestamp", "item_id", "position", "click"}
        missing = required.difference(fieldnames)
        if missing:
            raise ValueError(f"missing Open Bandit columns: {sorted(missing)}")
        if "propensity_score" in fieldnames:
            propensity_column = "propensity_score"
        elif "action_prob" in fieldnames:
            propensity_column = "action_prob"
        else:
            raise ValueError(
                "missing Open Bandit propensity column: expected propensity_score or action_prob"
            )
        numeric_columns, categorical_columns = _open_bandit_context_columns(fieldnames)
        for index, row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            interactions.append(
                OpenBanditInteraction(
                    timestamp=row["timestamp"],
                    item_id=_read_int(row, "item_id"),
                    position=_read_int(row, "position"),
                    click=_read_binary(row, "click"),
                    propensity_score=_read_float(row, propensity_column),
                    context=tuple(_read_float(row, name) for name in numeric_columns),
                    categorical_context=tuple(row[name] for name in categorical_columns),
                )
            )
    if not interactions:
        raise ValueError("Open Bandit file produced no rows")
    return tuple(interactions)


@dataclass(frozen=True, slots=True)
class KuaiRandInteraction:
    user_id: int
    video_id: int
    time_ms: int
    date: int
    hourmin: int
    tab: int
    is_random: bool
    is_click: float
    is_like: float
    is_follow: float
    is_comment: float
    is_forward: float
    is_hate: float
    long_view: float
    play_time_ms: float
    duration_ms: float

    def __post_init__(self) -> None:
        if self.user_id < 0 or self.video_id < 0 or self.time_ms < 0:
            raise ValueError("user_id, video_id and time_ms must be non-negative")
        for name, value in (
            ("is_click", self.is_click),
            ("is_like", self.is_like),
            ("is_follow", self.is_follow),
            ("is_comment", self.is_comment),
            ("is_forward", self.is_forward),
            ("is_hate", self.is_hate),
            ("long_view", self.long_view),
        ):
            if value not in {0.0, 1.0}:
                raise ValueError(f"{name} must be binary")
        if self.play_time_ms < 0 or self.duration_ms < 0:
            raise ValueError("play_time_ms and duration_ms must be non-negative")


# Named reference profile for reproducible examples/tests only. Adapters never
# select it implicitly; a research protocol must pass weights or a reward function.
DEFAULT_KUAIRAND_REWARD_WEIGHTS: Mapping[str, float] = {
    "is_click": 1.0,
    "long_view": 0.35,
    "is_like": 0.25,
    "is_follow": 0.50,
    "is_comment": 0.20,
    "is_forward": 0.20,
    "is_hate": -0.50,
}


def load_kuairand(
    path: PathLike,
    *,
    max_rows: int | None = None,
) -> tuple[KuaiRandInteraction, ...]:
    """Load sequential KuaiRand recommendation logs.

    ``is_rand`` is retained as intervention provenance only. It is never
    converted into an action propensity because the row does not identify that
    probability or the full candidate action set.
    """

    if max_rows is not None and max_rows <= 0:
        raise ValueError("max_rows must be positive when provided")
    rows: list[KuaiRandInteraction] = []
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        required = {
            "user_id",
            "video_id",
            "time_ms",
            "date",
            "hourmin",
            "tab",
            "is_rand",
            "is_click",
            "is_like",
            "is_follow",
            "is_comment",
            "is_forward",
            "is_hate",
            "long_view",
            "play_time_ms",
            "duration_ms",
        }
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing KuaiRand columns: {sorted(missing)}")
        for index, row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            is_random = _read_binary(row, "is_rand")
            rows.append(
                KuaiRandInteraction(
                    user_id=_read_int(row, "user_id"),
                    video_id=_read_int(row, "video_id"),
                    time_ms=_read_int(row, "time_ms"),
                    date=_read_int(row, "date"),
                    hourmin=_read_int(row, "hourmin"),
                    tab=_read_int(row, "tab"),
                    is_random=bool(is_random),
                    is_click=_read_binary(row, "is_click"),
                    is_like=_read_binary(row, "is_like"),
                    is_follow=_read_binary(row, "is_follow"),
                    is_comment=_read_binary(row, "is_comment"),
                    is_forward=_read_binary(row, "is_forward"),
                    is_hate=_read_binary(row, "is_hate"),
                    long_view=_read_binary(row, "long_view"),
                    play_time_ms=_read_float(row, "play_time_ms"),
                    duration_ms=_read_float(row, "duration_ms"),
                )
            )
    if not rows:
        raise ValueError("KuaiRand file produced no rows")
    return tuple(rows)


def kuairand_reward(
    row: KuaiRandInteraction,
    *,
    weights: Mapping[str, float],
) -> float:
    """Scalarize multi-feedback only under an explicit experiment objective."""

    if not weights:
        raise ValueError("KuaiRand reward weights cannot be empty")
    signals = {
        "is_click": row.is_click,
        "long_view": row.long_view,
        "is_like": row.is_like,
        "is_follow": row.is_follow,
        "is_comment": row.is_comment,
        "is_forward": row.is_forward,
        "is_hate": row.is_hate,
    }
    unknown = set(weights).difference(signals)
    if unknown:
        raise ValueError(f"unknown KuaiRand reward signals: {sorted(unknown)}")
    return fsum(float(weights[name]) * signals[name] for name in weights)
