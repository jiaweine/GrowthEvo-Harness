from __future__ import annotations

"""Export official Open Bandit Dataset evidence into GrowthEvo locked-OPE JSONL.

This script is intentionally standalone. Run it in a separate environment that
can install the official ``obp`` stack; it does not import GrowthEvo itself.
The output contract is then consumed by GrowthEvo's Python 3.11+ locked runner.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


def _value_3d(array: Any, row: int, action: int, position: int) -> float:
    return float(array[row][action][position])


def _position(feedback: Mapping[str, Any], row: int) -> int:
    positions = feedback.get("position")
    return 0 if positions is None else int(positions[row])


def build_locked_ope_rows(
    feedback: Mapping[str, Any],
    action_dist: Any,
    q_hat: Any,
    record_ids: Sequence[str],
    *,
    cluster_ids: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Convert OBP-style arrays into GrowthEvo's generic logged-bandit contract."""

    n_rounds = int(feedback["n_rounds"])
    if n_rounds <= 0:
        raise ValueError("feedback must contain at least one round")
    if len(record_ids) != n_rounds:
        raise ValueError("record_ids must align with feedback")
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("record_ids must be unique")
    if any(not isinstance(value, str) or not value for value in record_ids):
        raise ValueError("record_ids must be non-empty strings")
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

        target_probability = _value_3d(action_dist, index, action, position)
        if not 0.0 <= target_probability <= 1.0:
            raise ValueError("target action probability must be in [0, 1]")

        probability_mass = sum(
            _value_3d(action_dist, index, candidate, position)
            for candidate in range(n_actions)
        )
        if abs(probability_mass - 1.0) > 1e-5:
            raise ValueError("target action probabilities must sum to 1 at each position")

        baseline_q = _value_3d(q_hat, index, action, position)
        target_q = sum(
            _value_3d(action_dist, index, candidate, position)
            * _value_3d(q_hat, index, candidate, position)
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


def _slice_3d(array: Any, start: int, stop: int) -> Any:
    return array[start:stop]


def _record_ids(dataset: Any, behavior_policy: str, campaign: str) -> List[str]:
    """Use the raw CSV index plus factual fields to keep IDs stable and auditable."""

    raw = dataset.data
    ids: List[str] = []
    for position, (source_index, row) in enumerate(raw.iterrows()):
        timestamp = str(row["timestamp"])
        item_id = int(row["item_id"])
        slot = int(row["position"])
        ids.append(
            "%s|%s|source=%s|ts=%s|item=%d|pos=%d|ordinal=%d"
            % (
                behavior_policy,
                campaign,
                source_index,
                timestamp,
                item_id,
                slot,
                position,
            )
        )
    if len(set(ids)) != len(ids):
        raise ValueError("constructed OBD record identities are not unique")
    return ids


def _fit_q(
    feedback: Mapping[str, Any],
    *,
    n_actions: int,
    action_context: Any,
    n_folds: int,
    random_state: int,
    q_model: str,
) -> Any:
    import numpy as np

    if q_model == "zero":
        positions = feedback.get("position")
        len_list = 1 if positions is None else int(np.max(positions)) + 1
        return np.zeros((int(feedback["n_rounds"]), n_actions, len_list), dtype=float)

    if q_model != "logistic":
        raise ValueError("q_model must be either 'logistic' or 'zero'")

    from obp.ope import RegressionModel
    from sklearn.linear_model import LogisticRegression

    model = RegressionModel(
        n_actions=n_actions,
        action_context=action_context,
        base_model=LogisticRegression(
            C=1.0,
            max_iter=1000,
            random_state=random_state,
        ),
    )
    kwargs: Dict[str, Any] = {
        "context": feedback["context"],
        "action": feedback["action"],
        "reward": feedback["reward"],
        "n_folds": n_folds,
        "random_state": random_state,
    }
    if feedback.get("position") is not None:
        kwargs["position"] = feedback["position"]
    return model.fit_predict(**kwargs)


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
    validation_fraction: float,
    n_sim: int,
    q_folds: int,
    q_model: str,
    random_state: int,
) -> Dict[str, Any]:
    if campaign not in {"all", "men", "women"}:
        raise ValueError("campaign must be one of: all, men, women")
    if not 0.1 <= validation_fraction <= 0.9:
        raise ValueError("validation_fraction must be in [0.1, 0.9]")
    if n_sim <= 0:
        raise ValueError("n_sim must be positive")
    if q_folds < 2:
        raise ValueError("q_folds must be at least 2")

    try:
        import obp
        from obp.dataset import OpenBanditDataset
        from obp.policy import BernoulliTS
    except ImportError as exc:
        raise RuntimeError(
            "This exporter must run in an isolated environment with the official "
            "Open Bandit Pipeline installed."
        ) from exc

    dataset_kwargs: Dict[str, Any] = {"campaign": campaign}
    if data_path is not None:
        dataset_kwargs["data_path"] = data_path

    behavior_dataset = OpenBanditDataset(behavior_policy="random", **dataset_kwargs)
    target_dataset = OpenBanditDataset(behavior_policy="bts", **dataset_kwargs)
    behavior_feedback = behavior_dataset.obtain_batch_bandit_feedback()
    target_feedback = target_dataset.obtain_batch_bandit_feedback()

    if behavior_dataset.n_actions != target_dataset.n_actions:
        raise ValueError("random and BTS datasets disagree on action-space size")
    if behavior_dataset.len_list != target_dataset.len_list:
        raise ValueError("random and BTS datasets disagree on slate length")

    behavior_n = int(behavior_feedback["n_rounds"])
    target_n = int(target_feedback["n_rounds"])
    behavior_split = int(behavior_n * validation_fraction)
    target_split = int(target_n * validation_fraction)
    if min(behavior_split, behavior_n - behavior_split, target_split, target_n - target_split) < q_folds:
        raise ValueError("each chronological window must contain at least q_folds rows")

    evaluation_policy = BernoulliTS(
        n_actions=behavior_dataset.n_actions,
        len_list=behavior_dataset.len_list,
        is_zozotown_prior=True,
        campaign=campaign,
        random_state=random_state,
    )
    action_dist = evaluation_policy.compute_batch_action_dist(
        n_sim=n_sim,
        n_rounds=behavior_n,
    )

    ids = _record_ids(behavior_dataset, "random", campaign)
    windows: List[Tuple[str, int, int]] = [
        ("validation", 0, behavior_split),
        ("holdout", behavior_split, behavior_n),
    ]
    for name, start, stop in windows:
        feedback_slice = _slice_feedback(behavior_feedback, start, stop)
        q_hat = _fit_q(
            feedback_slice,
            n_actions=behavior_dataset.n_actions,
            action_context=behavior_feedback["action_context"],
            n_folds=q_folds,
            random_state=random_state + (0 if name == "validation" else 1),
            q_model=q_model,
        )
        rows = build_locked_ope_rows(
            feedback_slice,
            _slice_3d(action_dist, start, stop),
            q_hat,
            ids[start:stop],
        )
        _write_jsonl(output_dir / (name + ".jsonl"), rows)

    validation_reference = float(target_feedback["reward"][:target_split].mean())
    holdout_reference = float(target_feedback["reward"][target_split:].mean())
    if not math.isfinite(validation_reference) or not math.isfinite(holdout_reference):
        raise ValueError("on-policy reference values must be finite")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ope_candidates.json").write_text(
        json.dumps(_default_candidates(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "growthevo.obd-export.v1",
        "obp_version": str(getattr(obp, "__version__", "unknown")),
        "campaign": campaign,
        "behavior_policy": "random",
        "evaluation_policy": "bts",
        "validation_fraction": validation_fraction,
        "validation_reference": validation_reference,
        "holdout_reference": holdout_reference,
        "behavior_rows": behavior_n,
        "evaluation_policy_rows": target_n,
        "n_sim": n_sim,
        "q_model": q_model,
        "q_folds": q_folds,
        "random_state": random_state,
        "protocol_note": (
            "paired chronological windows: random-policy evidence and BTS on-policy "
            "reference are split at the same relative fraction; Q predictions are "
            "cross-fitted independently inside each random-policy window"
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
    parser.add_argument("--validation-fraction", type=float, default=0.5)
    parser.add_argument("--n-sim", type=int, default=100000)
    parser.add_argument("--q-folds", type=int, default=3)
    parser.add_argument("--q-model", choices=["logistic", "zero"], default="logistic")
    parser.add_argument("--random-state", type=int, default=12345)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    manifest = export_obd_pair(
        campaign=args.campaign,
        output_dir=args.output_dir,
        data_path=args.data_path,
        validation_fraction=args.validation_fraction,
        n_sim=args.n_sim,
        q_folds=args.q_folds,
        q_model=args.q_model,
        random_state=args.random_state,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
