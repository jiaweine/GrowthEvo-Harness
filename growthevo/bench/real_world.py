from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from gzip import open as gzip_open
from pathlib import Path
import csv
from math import fsum
from typing import Callable, Iterable, Literal, Mapping, TextIO

from growthevo.causal.dr_learner import LoggedTreatmentRecord
from growthevo.models import Channel
from growthevo.rl.ope import LoggedBanditRecord
from growthevo.training.trajectory import PlannerTransition


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
    return int(_read_float(row, key))


@dataclass(frozen=True, slots=True)
class CriteoUpliftData:
    """Randomized advertising records adapted to GrowthEvo's causal contract.

    The randomized assignment column is the treatment. The post-assignment
    ``exposure`` field is intentionally not used as treatment because doing so
    would condition on a downstream variable and break the randomized design.
    """

    records: tuple[LoggedTreatmentRecord, ...]
    treatment_propensity: float
    outcome_name: Literal["visit", "conversion"]


@dataclass(frozen=True, slots=True)
class RandomizedTargetingResult:
    sample_size: int
    selected_fraction: float
    policy_value: float
    treat_none_value: float
    treat_all_value: float
    incremental_value_vs_none: float


def load_criteo_uplift(
    path: PathLike,
    *,
    outcome: Literal["visit", "conversion"] = "visit",
    max_rows: int | None = None,
    treatment_propensity: float | None = None,
) -> CriteoUpliftData:
    """Load the public Criteo randomized uplift benchmark.

    The official file contains twelve dense anonymized features named f0..f11,
    randomized ``treatment``, two binary outcomes, and a post-treatment exposure
    indicator. When the original assignment probability is not supplied, the
    empirical randomized arm share in the loaded cohort is used.
    """

    if max_rows is not None and max_rows <= 0:
        raise ValueError("max_rows must be positive when provided")
    if treatment_propensity is not None and not 0 < treatment_propensity < 1:
        raise ValueError("treatment_propensity must be in (0, 1)")

    feature_names = tuple(f"f{index}" for index in range(12))
    raw: list[tuple[tuple[float, ...], bool, float]] = []
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        required = set(feature_names) | {"treatment", outcome}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing Criteo columns: {sorted(missing)}")
        for index, row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            features = tuple(_read_float(row, name) for name in feature_names)
            treated = bool(_read_int(row, "treatment"))
            y = _read_float(row, outcome)
            raw.append((features, treated, y))

    if not raw:
        raise ValueError("Criteo file produced no rows")
    observed_propensity = fsum(1.0 for _, treated, _ in raw if treated) / len(raw)
    propensity = treatment_propensity or observed_propensity
    if not 0 < propensity < 1:
        raise ValueError("loaded cohort must contain both treatment and control")

    action_propensities = {
        Channel.NO_TREATMENT: 1.0 - propensity,
        Channel.ADS: propensity,
    }
    records = tuple(
        LoggedTreatmentRecord(
            unit_id=f"criteo-{index}",
            features=features,
            action=Channel.ADS if treated else Channel.NO_TREATMENT,
            outcome=y,
            action_propensities=action_propensities,
        )
        for index, (features, treated, y) in enumerate(raw)
    )
    return CriteoUpliftData(
        records=records,
        treatment_propensity=propensity,
        outcome_name=outcome,
    )


def evaluate_randomized_targeting(
    records: Iterable[LoggedTreatmentRecord],
    scores: Iterable[float],
    *,
    selected_fraction: float,
    treatment: Channel = Channel.ADS,
) -> RandomizedTargetingResult:
    """Evaluate a top-score treatment policy with randomized inverse weighting.

    This metric evaluates the actual targeting decision instead of treating
    response prediction as uplift. It is appropriate when the source cohort was
    randomized and the assignment probabilities in ``records`` are trustworthy.
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

    def __post_init__(self) -> None:
        if self.position < 0:
            raise ValueError("position must be non-negative")
        if not 0 < self.propensity_score <= 1:
            raise ValueError("propensity_score must be in (0, 1]")


def _open_bandit_feature_columns(fieldnames: Iterable[str]) -> tuple[str, ...]:
    names = list(fieldnames)
    prefixes = ("user_feature", "user-item_affinity", "user_item_affinity")
    return tuple(name for name in names if name.startswith(prefixes))


def load_open_bandit(
    path: PathLike,
    *,
    max_rows: int | None = None,
) -> tuple[OpenBanditInteraction, ...]:
    """Load Open Bandit Dataset impressions while preserving true propensities."""

    if max_rows is not None and max_rows <= 0:
        raise ValueError("max_rows must be positive when provided")
    interactions: list[OpenBanditInteraction] = []
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "item_id", "position", "click", "propensity_score"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"missing Open Bandit columns: {sorted(missing)}")
        feature_columns = _open_bandit_feature_columns(reader.fieldnames or ())
        for index, row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            interactions.append(
                OpenBanditInteraction(
                    timestamp=row["timestamp"],
                    item_id=_read_int(row, "item_id"),
                    position=_read_int(row, "position"),
                    click=_read_float(row, "click"),
                    propensity_score=_read_float(row, "propensity_score"),
                    context=tuple(_read_float(row, name) for name in feature_columns),
                )
            )
    if not interactions:
        raise ValueError("Open Bandit file produced no rows")
    return tuple(interactions)


BanditScalarModel = Callable[[OpenBanditInteraction], float]


def open_bandit_to_ope(
    interactions: Iterable[OpenBanditInteraction],
    *,
    target_action_probability: BanditScalarModel,
    baseline_q: BanditScalarModel,
    target_q: BanditScalarModel,
) -> tuple[LoggedBanditRecord, ...]:
    """Adapt real Open Bandit impressions to GrowthEvo's OPE estimator input."""

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

    ``is_rand`` is retained as an intervention marker only. It is not converted
    into a propensity score because that would manufacture information that is
    not present in the interaction row.
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
            rows.append(
                KuaiRandInteraction(
                    user_id=_read_int(row, "user_id"),
                    video_id=_read_int(row, "video_id"),
                    time_ms=_read_int(row, "time_ms"),
                    date=_read_int(row, "date"),
                    hourmin=_read_int(row, "hourmin"),
                    tab=_read_int(row, "tab"),
                    is_random=bool(_read_int(row, "is_rand")),
                    is_click=_read_float(row, "is_click"),
                    is_like=_read_float(row, "is_like"),
                    is_follow=_read_float(row, "is_follow"),
                    is_comment=_read_float(row, "is_comment"),
                    is_forward=_read_float(row, "is_forward"),
                    is_hate=_read_float(row, "is_hate"),
                    long_view=_read_float(row, "long_view"),
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
    weights: Mapping[str, float] = DEFAULT_KUAIRAND_REWARD_WEIGHTS,
) -> float:
    """Compose an explicit multi-feedback reward for sequential experiments."""

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


def kuairand_to_planner_transitions(
    interactions: Iterable[KuaiRandInteraction],
    *,
    max_steps_per_trajectory: int = 100,
    reward_weights: Mapping[str, float] = DEFAULT_KUAIRAND_REWARD_WEIGHTS,
) -> tuple[PlannerTransition, ...]:
    """Create leakage-aware sequential training samples from KuaiRand logs.

    Observation features are computed from information available before the
    current feedback. Logged post-action feedback contributes only to reward and
    to the next step's history statistics.
    """

    if max_steps_per_trajectory <= 0:
        raise ValueError("max_steps_per_trajectory must be positive")
    by_user: dict[int, list[KuaiRandInteraction]] = defaultdict(list)
    for row in interactions:
        by_user[row.user_id].append(row)
    if not by_user:
        raise ValueError("at least one KuaiRand interaction is required")

    transitions: list[PlannerTransition] = []
    for user_id in sorted(by_user):
        rows = sorted(by_user[user_id], key=lambda row: (row.time_ms, row.video_id))
        prior_reward_sum = 0.0
        prior_click_sum = 0.0
        prior_long_view_sum = 0.0
        for offset, row in enumerate(rows):
            chunk = offset // max_steps_per_trajectory
            step_index = offset % max_steps_per_trajectory
            history_count = offset
            observation = {
                "user_id": user_id,
                "date": row.date,
                "hourmin": row.hourmin,
                "tab": row.tab,
                "random_intervention": row.is_random,
                "history_count": history_count,
                "prior_mean_reward": prior_reward_sum / history_count if history_count else 0.0,
                "prior_click_rate": prior_click_sum / history_count if history_count else 0.0,
                "prior_long_view_rate": prior_long_view_sum / history_count if history_count else 0.0,
            }
            reward = kuairand_reward(row, weights=reward_weights)
            done = step_index == max_steps_per_trajectory - 1 or offset == len(rows) - 1
            transitions.append(
                PlannerTransition(
                    trajectory_id=f"kuairand-user-{user_id}-chunk-{chunk}",
                    step_index=step_index,
                    action=f"recommend_video:{row.video_id}",
                    observation=observation,
                    reward=reward,
                    done=done,
                    legal_action=True,
                    tool_success=True,
                )
            )
            prior_reward_sum += reward
            prior_click_sum += row.is_click
            prior_long_view_sum += row.long_view
    return tuple(transitions)
