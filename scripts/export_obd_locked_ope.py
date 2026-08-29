from __future__ import annotations

"""Export official Open Bandit Dataset evidence into GrowthEvo locked-OPE JSONL.

The exporter intentionally keeps Open Bandit Pipeline optional.  It also avoids
materialising tensors whose first axis is the full logged-data size.  The
production BernoulliTS policy is context-free, so its Monte-Carlo action
probabilities are stored once as ``(n_actions, len_list)``.  Logistic reward
models are still fit with OBP's ``RegressionModel.fit`` semantics, but only the
two OPE quantities needed per row are retained: factual ``Q(x,a)`` and target
policy ``E_pi[Q(x,A)]``.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple


def _position(feedback: Mapping[str, Any], row: int) -> int:
    positions = feedback.get("position")
    return 0 if positions is None else int(positions[row])


def _is_shared_action_dist(action_dist: Any) -> bool:
    """Return whether action probabilities omit the round axis.

    Supports both numpy arrays and the nested-list fixtures used by core tests.
    """

    ndim = getattr(action_dist, "ndim", None)
    if ndim is not None:
        if ndim not in {2, 3}:
            raise ValueError("action_dist must be 2D shared or 3D per-round probabilities")
        return bool(ndim == 2)
    try:
        first_value = action_dist[0][0]
    except (IndexError, KeyError, TypeError) as exc:
        raise ValueError("action_dist must be a non-empty 2D or 3D array") from exc
    return not hasattr(first_value, "__len__")


def _action_probability(
    action_dist: Any,
    row: int,
    action: int,
    position: int,
) -> float:
    if _is_shared_action_dist(action_dist):
        return float(action_dist[action][position])
    return float(action_dist[row][action][position])


def _q_value(q_hat: Any, row: int, action: int, position: int) -> float:
    return float(q_hat[row][action][position])


def _validate_action_probability_mass(
    action_dist: Any,
    *,
    n_actions: int,
    positions: Iterable[int],
    row: int = 0,
) -> None:
    for position in sorted(set(int(value) for value in positions)):
        probability_mass = sum(
            _action_probability(action_dist, row, candidate, position)
            for candidate in range(n_actions)
        )
        if abs(probability_mass - 1.0) > 1e-5:
            raise ValueError("target action probabilities must sum to 1 at each position")


def _validate_record_ids(record_ids: Sequence[str], n_rounds: int) -> None:
    if len(record_ids) != n_rounds:
        raise ValueError("record_ids must align with feedback")
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("record_ids must be unique")
    if any(not isinstance(value, str) or not value for value in record_ids):
        raise ValueError("record_ids must be non-empty strings")


def build_locked_ope_rows(
    feedback: Mapping[str, Any],
    action_dist: Any,
    q_hat: Any,
    record_ids: Sequence[str],
    *,
    cluster_ids: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Convert OBP-style arrays into GrowthEvo's generic logged-bandit contract.

    ``action_dist`` may be the historical 3D OBP tensor or a shared 2D
    distribution.  The latter is equivalent for the replicated context-free
    BernoulliTS production policy and avoids an O(n_rounds) probability tile.
    """

    n_rounds = int(feedback["n_rounds"])
    if n_rounds <= 0:
        raise ValueError("feedback must contain at least one round")
    _validate_record_ids(record_ids, n_rounds)
    if cluster_ids is not None and len(cluster_ids) != n_rounds:
        raise ValueError("cluster_ids must align with feedback")

    n_actions = int(feedback["n_actions"])
    if n_actions <= 0:
        raise ValueError("n_actions must be positive")

    rows: List[Dict[str, Any]] = []
    for index in range(n_rounds):
        action = int(feedback["action"][index])
        position = _position(feedback, index)
        behavior_propensity = float(feedback["pscore"][index])
        reward = float(feedback["reward"][index])
        if not 0.0 < behavior_propensity <= 1.0:
            raise ValueError("behavior propensity must be in (0, 1]")
        if not math.isfinite(reward):
            raise ValueError("reward must be finite")

        target_probability = _action_probability(
            action_dist, index, action, position
        )
        if not 0.0 <= target_probability <= 1.0:
            raise ValueError("target action probability must be in [0, 1]")
        _validate_action_probability_mass(
            action_dist,
            n_actions=n_actions,
            positions=(position,),
            row=index,
        )

        baseline_q = _q_value(q_hat, index, action, position)
        target_q = sum(
            _action_probability(action_dist, index, candidate, position)
            * _q_value(q_hat, index, candidate, position)
            for candidate in range(n_actions)
        )
        if not math.isfinite(baseline_q) or not math.isfinite(target_q):
            raise ValueError("Q predictions must be finite")

        cluster_id = None if cluster_ids is None else cluster_ids[index]
        rows.append(
            {
                "reward": reward,
                "behavior_propensity": behavior_propensity,
                "target_action_probability": target_probability,
                "baseline_q": baseline_q,
                "target_q": target_q,
                "record_id": record_ids[index],
                "cluster_id": cluster_id,
            }
        )
    return rows


def build_locked_ope_rows_from_terms(
    feedback: Mapping[str, Any],
    action_dist: Any,
    baseline_q: Sequence[float],
    target_q: Sequence[float],
    record_ids: Sequence[str],
    *,
    cluster_ids: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Build rows when compact factual/target Q terms are already available."""

    n_rounds = int(feedback["n_rounds"])
    _validate_record_ids(record_ids, n_rounds)
    if len(baseline_q) != n_rounds or len(target_q) != n_rounds:
        raise ValueError("compact Q terms must align with feedback")
    if cluster_ids is not None and len(cluster_ids) != n_rounds:
        raise ValueError("cluster_ids must align with feedback")
    return list(
        _iter_locked_ope_rows_from_terms(
            feedback,
            action_dist,
            baseline_q,
            target_q,
            iter(record_ids),
            cluster_ids=cluster_ids,
        )
    )


def _iter_locked_ope_rows_from_terms(
    feedback: Mapping[str, Any],
    action_dist: Any,
    baseline_q: Sequence[float],
    target_q: Sequence[float],
    record_ids: Iterable[str],
    *,
    cluster_ids: Optional[Sequence[Any]] = None,
) -> Iterator[Dict[str, Any]]:
    """Yield compact OPE rows without retaining millions of dictionaries."""

    n_rounds = int(feedback["n_rounds"])
    n_actions = int(feedback["n_actions"])
    if n_rounds <= 0:
        raise ValueError("feedback must contain at least one round")
    if n_actions <= 0:
        raise ValueError("n_actions must be positive")
    if len(baseline_q) != n_rounds or len(target_q) != n_rounds:
        raise ValueError("compact Q terms must align with feedback")
    if cluster_ids is not None and len(cluster_ids) != n_rounds:
        raise ValueError("cluster_ids must align with feedback")

    positions = (
        [0]
        if feedback.get("position") is None
        else [int(value) for value in feedback["position"]]
    )
    if _is_shared_action_dist(action_dist):
        _validate_action_probability_mass(
            action_dist,
            n_actions=n_actions,
            positions=positions,
        )

    id_iter = iter(record_ids)
    for index in range(n_rounds):
        try:
            record_id = next(id_iter)
        except StopIteration as exc:
            raise ValueError("record_ids must align with feedback") from exc
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("record_ids must be non-empty strings")

        action = int(feedback["action"][index])
        position = _position(feedback, index)
        behavior_propensity = float(feedback["pscore"][index])
        reward = float(feedback["reward"][index])
        factual_q = float(baseline_q[index])
        policy_q = float(target_q[index])
        if not 0.0 < behavior_propensity <= 1.0:
            raise ValueError("behavior propensity must be in (0, 1]")
        if not all(math.isfinite(value) for value in (reward, factual_q, policy_q)):
            raise ValueError("reward and compact Q terms must be finite")

        target_probability = _action_probability(
            action_dist,
            index if not _is_shared_action_dist(action_dist) else 0,
            action,
            position,
        )
        if not 0.0 <= target_probability <= 1.0:
            raise ValueError("target action probability must be in [0, 1]")
        if not _is_shared_action_dist(action_dist):
            _validate_action_probability_mass(
                action_dist,
                n_actions=n_actions,
                positions=(position,),
                row=index,
            )

        cluster_id = None if cluster_ids is None else cluster_ids[index]
        yield {
            "reward": reward,
            "behavior_propensity": behavior_propensity,
            "target_action_probability": target_probability,
            "baseline_q": factual_q,
            "target_q": policy_q,
            "record_id": record_id,
            "cluster_id": cluster_id,
        }

    try:
        next(id_iter)
    except StopIteration:
        return
    raise ValueError("record_ids must align with feedback")


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":")))
            handle.write("\n")


def _slice_feedback(feedback: Mapping[str, Any], start: int, stop: int) -> Dict[str, Any]:
    if not 0 <= start < stop <= int(feedback["n_rounds"]):
        raise ValueError("invalid feedback slice")
    sliced: Dict[str, Any] = {
        "n_rounds": stop - start,
        "n_actions": int(feedback["n_actions"]),
        "action_context": feedback["action_context"],
    }
    for key in ("action", "position", "reward", "pscore", "context"):
        value = feedback.get(key)
        sliced[key] = None if value is None else value[start:stop]
    return sliced


def _record_id_iter(
    dataset: Any,
    behavior_policy: str,
    campaign: str,
    start: int,
    stop: int,
) -> Iterator[str]:
    """Generate stable IDs lazily instead of retaining millions of strings."""

    raw = dataset.data.iloc[start:stop]
    columns = raw[["timestamp", "item_id", "position"]]
    for ordinal, values in enumerate(
        columns.itertuples(index=True, name=None),
        start=start,
    ):
        source_index, timestamp, item_id, slot = values
        yield (
            f"{behavior_policy}|{campaign}|source={source_index}|ts={timestamp}"
            f"|item={int(item_id)}|pos={int(slot)}|ordinal={ordinal}"
        )


def _regression_model_kwargs(
    *,
    n_actions: int,
    len_list: int,
    action_context: Any,
) -> Dict[str, Any]:
    """Keep the OBP slate width explicit instead of relying on len_list=1 default."""

    if n_actions <= 0:
        raise ValueError("n_actions must be positive")
    if len_list <= 0:
        raise ValueError("len_list must be positive")
    return {
        "n_actions": n_actions,
        "len_list": len_list,
        "action_context": action_context,
    }


def _sigmoid(values: Any) -> Any:
    import numpy as np

    array = np.asarray(values, dtype=float)
    result = np.empty_like(array, dtype=float)
    positive = array >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-array[positive]))
    exp_values = np.exp(array[~positive])
    result[~positive] = exp_values / (1.0 + exp_values)
    return result


def _fill_compact_logistic_predictions(
    model: Any,
    *,
    context: Any,
    action: Any,
    position: Any,
    test_indices: Any,
    action_dist: Any,
    baseline_q: Any,
    target_q: Any,
    prediction_batch_size: int,
) -> None:
    """Predict only q(x,a_logged) and E_pi[q(x,A)] for held-out rows."""

    import numpy as np

    shared = np.asarray(action_dist, dtype=float)
    if shared.ndim != 2:
        raise ValueError("compact logistic prediction requires a shared 2D action_dist")
    if prediction_batch_size <= 0:
        raise ValueError("prediction_batch_size must be positive")

    action_context = np.asarray(model.action_context, dtype=float)
    context_width = int(context.shape[1])
    for pos in range(model.len_list):
        pos_indices = test_indices[position[test_indices] == pos]
        if pos_indices.size == 0:
            continue
        fitted = model.base_model_list[pos]
        classes = np.asarray(fitted.classes_)
        if classes.shape != (2,) or not np.array_equal(classes, np.asarray([0, 1])):
            raise ValueError("logistic Q model must be fit on binary rewards {0, 1}")
        coefficients = np.asarray(fitted.coef_, dtype=float)
        if coefficients.shape[0] != 1:
            raise ValueError("expected binary logistic-regression coefficients")
        coefficient = coefficients[0]
        if coefficient.size != context_width + action_context.shape[1]:
            raise ValueError("unexpected logistic feature width")
        context_coefficient = coefficient[:context_width]
        action_coefficient = coefficient[context_width:]
        action_offsets = action_context @ action_coefficient
        intercept = float(np.asarray(fitted.intercept_).reshape(-1)[0])
        target_weights = shared[:, pos]

        for batch_start in range(0, pos_indices.size, prediction_batch_size):
            batch_indices = pos_indices[
                batch_start : batch_start + prediction_batch_size
            ]
            context_batch = np.asarray(context[batch_indices], dtype=float)
            base_logit = context_batch @ context_coefficient + intercept
            baseline_q[batch_indices] = _sigmoid(
                base_logit + action_offsets[action[batch_indices]]
            )
            all_action_probabilities = _sigmoid(
                base_logit[:, None] + action_offsets[None, :]
            )
            target_q[batch_indices] = all_action_probabilities @ target_weights


def _fit_q_terms(
    feedback: Mapping[str, Any],
    action_dist: Any,
    *,
    n_actions: int,
    len_list: int,
    action_context: Any,
    n_folds: int,
    random_state: int,
    q_model: str,
    prediction_batch_size: int = 50_000,
) -> Tuple[Any, Any]:
    """Cross-fit compact Q terms while preserving OBP RegressionModel fit semantics."""

    import numpy as np

    n_rounds = int(feedback["n_rounds"])
    if len_list <= 0:
        raise ValueError("len_list must be positive")
    if n_folds < 2:
        raise ValueError("n_folds must be at least 2")
    if q_model == "zero":
        return np.zeros(n_rounds, dtype=float), np.zeros(n_rounds, dtype=float)
    if q_model != "logistic":
        raise ValueError("q_model must be either 'logistic' or 'zero'")
    if not _is_shared_action_dist(action_dist):
        raise ValueError("memory-bounded logistic Q requires a shared action distribution")

    from obp.ope import RegressionModel
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import KFold

    context = np.asarray(feedback["context"])
    action = np.asarray(feedback["action"], dtype=int)
    reward = np.asarray(feedback["reward"], dtype=float)
    if feedback.get("position") is None:
        position = np.zeros(n_rounds, dtype=int)
    else:
        position = np.asarray(feedback["position"], dtype=int)

    baseline_q = np.empty(n_rounds, dtype=float)
    target_q = np.empty(n_rounds, dtype=float)
    model = RegressionModel(
        **_regression_model_kwargs(
            n_actions=n_actions,
            len_list=len_list,
            action_context=action_context,
        ),
        base_model=LogisticRegression(
            C=1.0,
            max_iter=1000,
            random_state=random_state,
        ),
    )
    splitter = KFold(n_splits=n_folds, shuffle=True, random_state=random_state)
    for train_indices, test_indices in splitter.split(context):
        model.fit(
            context=context[train_indices],
            action=action[train_indices],
            reward=reward[train_indices],
            position=position[train_indices],
        )
        _fill_compact_logistic_predictions(
            model,
            context=context,
            action=action,
            position=position,
            test_indices=test_indices,
            action_dist=action_dist,
            baseline_q=baseline_q,
            target_q=target_q,
            prediction_batch_size=prediction_batch_size,
        )
    if not np.isfinite(baseline_q).all() or not np.isfinite(target_q).all():
        raise ValueError("cross-fitted compact Q terms must be finite")
    return baseline_q, target_q


def _target_reference_from_csv(
    source: str | Path,
    *,
    validation_fraction: float,
    expected_n_actions: int,
    expected_len_list: int,
    chunksize: int = 250_000,
) -> Tuple[float, float, int]:
    """Load only timestamp/reward/action/position columns for the BTS reference.

    The full BTS ``all`` log is much larger than the random-policy OPE evidence.
    Retaining its user/item features is unnecessary because the reference is the
    factual on-policy click mean.  Timestamps and rewards are compacted while
    reading chunks, then ordered chronologically before the predeclared split.
    """

    import numpy as np
    import pandas as pd

    if chunksize <= 0:
        raise ValueError("chunksize must be positive")
    timestamps: list[Any] = []
    rewards: list[Any] = []
    row_count = 0
    max_action = -1
    raw_positions: set[int] = set()
    for chunk in pd.read_csv(
        source,
        usecols=["timestamp", "item_id", "position", "click"],
        chunksize=chunksize,
    ):
        if chunk.empty:
            continue
        parsed = pd.to_datetime(chunk["timestamp"], utc=True, errors="raise")
        timestamps.append(parsed.astype("int64").to_numpy(copy=True))
        reward_chunk = chunk["click"].to_numpy(dtype=np.uint8, copy=True)
        if not np.isin(reward_chunk, [0, 1]).all():
            raise ValueError("Open Bandit click reference must be binary")
        rewards.append(reward_chunk)
        max_action = max(max_action, int(chunk["item_id"].max()))
        raw_positions.update(int(value) for value in chunk["position"].unique())
        row_count += int(chunk.shape[0])

    if row_count == 0:
        raise ValueError("target-policy reference CSV produced no rows")
    target_n_actions = max_action + 1
    target_len_list = len(raw_positions)
    if target_n_actions != expected_n_actions:
        raise ValueError("random and BTS datasets disagree on action-space size")
    if target_len_list != expected_len_list:
        raise ValueError("random and BTS datasets disagree on slate length")

    timestamp_values = np.concatenate(timestamps)
    reward_values = np.concatenate(rewards)
    # OpenBanditDataset sorts one timestamp column with pandas' default quicksort.
    # ISO-8601 timestamps are converted to int64 only to compact memory here.
    order = np.argsort(timestamp_values, kind="quicksort")
    split = int(row_count * validation_fraction)
    if min(split, row_count - split) <= 0:
        raise ValueError("target reference split produced an empty window")
    validation_reference = float(reward_values[order[:split]].mean())
    holdout_reference = float(reward_values[order[split:]].mean())
    return validation_reference, holdout_reference, row_count


def _target_csv_source(
    behavior_dataset: Any,
    *,
    campaign: str,
    data_path: Optional[Path],
    target_csv_url: Optional[str],
) -> str | Path:
    if target_csv_url is not None:
        if not target_csv_url:
            raise ValueError("target_csv_url cannot be empty")
        return target_csv_url
    if data_path is not None:
        return data_path / "bts" / campaign / f"{campaign}.csv"
    # OpenBanditDataset rewrites data_path to <root>/<policy>/<campaign>.
    root = Path(behavior_dataset.data_path).parents[1]
    return root / "bts" / campaign / f"{campaign}.csv"


def _default_candidates() -> List[Dict[str, Any]]:
    return [
        {"name": "beta-cf5", "estimator": "beta_ips", "beta_folds": 5},
        {"name": "dr", "estimator": "doubly_robust"},
        {"name": "ips", "estimator": "ips"},
        {"name": "snips", "estimator": "self_normalized_ips"},
        {"name": "switch-5", "estimator": "switch_dr", "switch_threshold": 5.0},
        {"name": "switch-10", "estimator": "switch_dr", "switch_threshold": 10.0},
        {"name": "dros-1", "estimator": "dr_os", "dr_os_lambda": 1.0},
        {"name": "dros-10", "estimator": "dr_os", "dr_os_lambda": 10.0},
        {"name": "meta-blue", "estimator": "meta_blue"},
    ]


def export_obd_pair(
    *,
    campaign: str,
    output_dir: Path,
    data_path: Optional[Path],
    dataset_source: Optional[str],
    validation_fraction: float,
    n_sim: int,
    q_folds: int,
    q_model: str,
    random_state: int,
    target_csv_url: Optional[str] = None,
    prediction_batch_size: int = 50_000,
) -> Dict[str, Any]:
    if campaign not in {"all", "men", "women"}:
        raise ValueError("campaign must be one of: all, men, women")
    if dataset_source is not None and not dataset_source:
        raise ValueError("dataset_source cannot be empty when provided")
    if not 0.1 <= validation_fraction <= 0.9:
        raise ValueError("validation_fraction must be in [0.1, 0.9]")
    if n_sim <= 0:
        raise ValueError("n_sim must be positive")
    if q_folds < 2:
        raise ValueError("q_folds must be at least 2")
    if prediction_batch_size <= 0:
        raise ValueError("prediction_batch_size must be positive")

    try:
        import obp
        from obp.dataset import OpenBanditDataset
        from obp.policy import BernoulliTS
    except ImportError as exc:
        raise RuntimeError(
            "Open Bandit support is not installed. Install GrowthEvo with the "
            "optional 'obd' extra or run this script in another environment "
            "that exposes a compatible obp API."
        ) from exc

    dataset_kwargs: Dict[str, Any] = {"campaign": campaign}
    if data_path is not None:
        dataset_kwargs["data_path"] = data_path
    if dataset_source is not None:
        resolved_dataset_source = dataset_source
    elif data_path is not None:
        resolved_dataset_source = f"local-path:{data_path.resolve()}"
    else:
        resolved_dataset_source = "obp-default-small-dataset"

    behavior_dataset = OpenBanditDataset(behavior_policy="random", **dataset_kwargs)
    behavior_feedback = behavior_dataset.obtain_batch_bandit_feedback()
    behavior_n = int(behavior_feedback["n_rounds"])
    behavior_split = int(behavior_n * validation_fraction)
    if min(behavior_split, behavior_n - behavior_split) < q_folds:
        raise ValueError("each random-policy window must contain at least q_folds rows")

    target_source = _target_csv_source(
        behavior_dataset,
        campaign=campaign,
        data_path=data_path,
        target_csv_url=target_csv_url,
    )
    validation_reference, holdout_reference, target_n = _target_reference_from_csv(
        target_source,
        validation_fraction=validation_fraction,
        expected_n_actions=behavior_dataset.n_actions,
        expected_len_list=behavior_dataset.len_list,
    )
    target_split = int(target_n * validation_fraction)
    if min(target_split, target_n - target_split) < q_folds:
        raise ValueError("each BTS reference window must contain at least q_folds rows")

    evaluation_policy = BernoulliTS(
        n_actions=behavior_dataset.n_actions,
        len_list=behavior_dataset.len_list,
        is_zozotown_prior=True,
        campaign=campaign,
        random_state=random_state,
    )
    # BernoulliTS is context-free.  OBP computes one Monte-Carlo distribution and
    # tiles it across n_rounds; requesting one round avoids the enormous no-op tile.
    action_dist = evaluation_policy.compute_batch_action_dist(
        n_sim=n_sim,
        n_rounds=1,
    )[0]
    _validate_action_probability_mass(
        action_dist,
        n_actions=behavior_dataset.n_actions,
        positions=range(behavior_dataset.len_list),
    )

    windows: List[Tuple[str, int, int]] = [
        ("validation", 0, behavior_split),
        ("holdout", behavior_split, behavior_n),
    ]
    for name, start, stop in windows:
        feedback_slice = _slice_feedback(behavior_feedback, start, stop)
        baseline_q, target_q = _fit_q_terms(
            feedback_slice,
            action_dist,
            n_actions=behavior_dataset.n_actions,
            len_list=behavior_dataset.len_list,
            action_context=behavior_feedback["action_context"],
            n_folds=q_folds,
            random_state=random_state + (0 if name == "validation" else 1),
            q_model=q_model,
            prediction_batch_size=prediction_batch_size,
        )
        rows = _iter_locked_ope_rows_from_terms(
            feedback_slice,
            action_dist,
            baseline_q,
            target_q,
            _record_id_iter(
                behavior_dataset,
                "random",
                campaign,
                start,
                stop,
            ),
        )
        _write_jsonl(output_dir / f"{name}.jsonl", rows)

    if not math.isfinite(validation_reference) or not math.isfinite(holdout_reference):
        raise ValueError("on-policy reference values must be finite")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ope_candidates.json").write_text(
        json.dumps(_default_candidates(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "growthevo.obd-export.v3",
        "obp_version": str(getattr(obp, "__version__", "unknown")),
        "dataset_source": resolved_dataset_source,
        "campaign": campaign,
        "behavior_policy": "random",
        "evaluation_policy": "bts",
        "reward_definition": "click",
        "split_strategy": "paired_chronological_relative_fraction",
        "validation_fraction": validation_fraction,
        "validation_reference": validation_reference,
        "holdout_reference": holdout_reference,
        "behavior_rows": behavior_n,
        "evaluation_policy_rows": target_n,
        "n_sim": n_sim,
        "q_model": q_model,
        "q_folds": q_folds,
        "slate_len": int(behavior_dataset.len_list),
        "random_state": random_state,
        "action_distribution_storage": "shared_context_free",
        "q_prediction_storage": "compact_factual_and_target",
        "q_backend": "obp-regression-fit+compact-logistic-predict-v1",
        "target_reference_loader": "chunked_reward_only",
        "prediction_batch_size": prediction_batch_size,
        "protocol_note": (
            "paired chronological windows: random-policy evidence and BTS on-policy "
            "reference are split at the same relative fraction; Q predictions are "
            "cross-fitted independently inside each random-policy window; the "
            "context-free BernoulliTS distribution is stored once rather than tiled"
        ),
    }
    (output_dir / "export_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Export official Open Bandit Dataset random→BTS evidence into the "
            "GrowthEvo locked-OPE JSONL contract."
        )
    )
    parser.add_argument("--campaign", choices=["all", "men", "women"], default="all")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--data-path", type=Path)
    parser.add_argument("--dataset-source")
    parser.add_argument(
        "--target-csv-url",
        help=(
            "Optional remote BTS campaign CSV. Useful for full data so only the "
            "smaller random-policy evidence file needs local disk space."
        ),
    )
    parser.add_argument("--validation-fraction", type=float, default=0.5)
    parser.add_argument("--n-sim", type=int, default=100000)
    parser.add_argument("--q-folds", type=int, default=3)
    parser.add_argument("--q-model", choices=["logistic", "zero"], default="logistic")
    parser.add_argument("--random-state", type=int, default=12345)
    parser.add_argument("--prediction-batch-size", type=int, default=50_000)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    manifest = export_obd_pair(
        campaign=args.campaign,
        output_dir=args.output_dir,
        data_path=args.data_path,
        dataset_source=args.dataset_source,
        validation_fraction=args.validation_fraction,
        n_sim=args.n_sim,
        q_folds=args.q_folds,
        q_model=args.q_model,
        random_state=args.random_state,
        target_csv_url=args.target_csv_url,
        prediction_batch_size=args.prediction_batch_size,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
