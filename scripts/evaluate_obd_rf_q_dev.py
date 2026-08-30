from __future__ import annotations

"""Validation-only comparison of logistic-Q and author-faithful random-forest Q.

This script is deliberately outside the locked OPE registry. It keeps the
logged-policy evidence and target-policy probabilities fixed, then replaces only
the nuisance reward model with the RandomForest configuration used in the
public Meta-OPE RecSys 2025 notebook:

- RandomForestClassifier(n_estimators=150, max_depth=5, n_jobs=-1,
  random_state=12345)
- OBP RegressionModel normal fitting
- 5-fold cross-fitting with pscore supplied
- global mean calibration: q_hat += reward.mean() - q_hat.mean()

No holdout reference or holdout rows are consumed by this comparator.
"""

import argparse
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


_RF_TREES = 150
_RF_MAX_DEPTH = 5
_RF_FOLDS = 5
_RF_RANDOM_STATE = 12345


def _json_cluster_identity(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_json_cluster_identity(item) for item in value)
    return value


def load_logged_rows(path: str | Path) -> tuple[LoggedBanditRecord, ...]:
    resolved = Path(path)
    rows: list[LoggedBanditRecord] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {resolved}:{line_number}")
            try:
                record_id = payload["record_id"]
                if not isinstance(record_id, str) or not record_id:
                    raise ValueError("record_id must be a non-empty string")
                rows.append(
                    LoggedBanditRecord(
                        reward=float(payload["reward"]),
                        behavior_propensity=float(payload["behavior_propensity"]),
                        target_action_probability=float(payload["target_action_probability"]),
                        baseline_q=float(payload["baseline_q"]),
                        target_q=float(payload["target_q"]),
                        cluster_id=_json_cluster_identity(payload.get("cluster_id")),
                        record_id=record_id,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid OPE row at {resolved}:{line_number}: {exc}") from exc
    if not rows:
        raise ValueError(f"{resolved} produced no OPE records")
    if len({row.record_id for row in rows}) != len(rows):
        raise ValueError("validation record IDs must be unique")
    return tuple(rows)


def _position_array(feedback: Mapping[str, Any]) -> Any:
    import numpy as np

    if feedback.get("position") is None:
        return np.zeros(int(feedback["n_rounds"]), dtype=int)
    return np.asarray(feedback["position"], dtype=int)


def _slice_feedback(feedback: Mapping[str, Any], stop: int) -> dict[str, Any]:
    n_rounds = int(feedback["n_rounds"])
    if not 0 < stop <= n_rounds:
        raise ValueError("validation row count must fit inside random-policy feedback")
    result: dict[str, Any] = {
        "n_rounds": stop,
        "n_actions": int(feedback["n_actions"]),
        "action_context": feedback["action_context"],
    }
    for key in ("action", "position", "reward", "pscore", "context"):
        value = feedback.get(key)
        result[key] = None if value is None else value[:stop]
    return result


def _shared_bts_action_dist(dataset: Any, *, campaign: str, n_sim: int, random_state: int) -> Any:
    import numpy as np
    from obp.policy import BernoulliTS

    policy = BernoulliTS(
        n_actions=dataset.n_actions,
        len_list=dataset.len_list,
        is_zozotown_prior=True,
        campaign=campaign,
        random_state=random_state,
    )
    action_dist = np.asarray(
        policy.compute_batch_action_dist(n_sim=n_sim, n_rounds=1)[0],
        dtype=float,
    )
    if action_dist.shape != (dataset.n_actions, dataset.len_list):
        raise ValueError("unexpected shared BTS action-distribution shape")
    if not np.allclose(action_dist.sum(axis=0), 1.0, atol=1e-6):
        raise ValueError("BTS action probabilities must sum to one at each position")
    return action_dist


def _validate_fixed_logged_evidence(
    rows: Sequence[LoggedBanditRecord],
    feedback: Mapping[str, Any],
    action_dist: Any,
) -> None:
    import numpy as np

    if len(rows) != int(feedback["n_rounds"]):
        raise ValueError("baseline JSONL must align with raw validation window")
    action = np.asarray(feedback["action"], dtype=int)
    reward = np.asarray(feedback["reward"], dtype=float)
    pscore = np.asarray(feedback["pscore"], dtype=float)
    position = _position_array(feedback)
    for index, row in enumerate(rows):
        if abs(row.reward - float(reward[index])) > 1e-12:
            raise ValueError("baseline JSONL reward does not match raw validation evidence")
        if abs(row.behavior_propensity - float(pscore[index])) > 1e-12:
            raise ValueError("baseline JSONL pscore does not match raw validation evidence")
        expected_target = float(action_dist[action[index], position[index]])
        if abs(row.target_action_probability - expected_target) > 1e-12:
            raise ValueError("baseline JSONL target probability does not match fixed BTS policy")


def fit_author_random_forest_q(
    feedback: Mapping[str, Any],
    *,
    action_dist: Any,
    random_state: int = _RF_RANDOM_STATE,
    n_folds: int = _RF_FOLDS,
) -> tuple[Any, float]:
    """Fit the public Meta-OPE OBD reward model and apply its mean calibration."""

    import numpy as np
    from obp.ope import RegressionModel
    from sklearn.ensemble import RandomForestClassifier

    if n_folds != _RF_FOLDS:
        raise ValueError("development protocol fixes random-forest Q at 5 folds")
    context = np.asarray(feedback["context"])
    action = np.asarray(feedback["action"], dtype=int)
    reward = np.asarray(feedback["reward"], dtype=float)
    pscore = np.asarray(feedback["pscore"], dtype=float)
    position = _position_array(feedback)
    model = RegressionModel(
        n_actions=int(feedback["n_actions"]),
        len_list=int(action_dist.shape[1]),
        action_context=feedback["action_context"],
        base_model=RandomForestClassifier(
            n_estimators=_RF_TREES,
            max_depth=_RF_MAX_DEPTH,
            n_jobs=-1,
            random_state=random_state,
        ),
    )
    q_hat = model.fit_predict(
        context=context,
        action=action,
        reward=reward,
        pscore=pscore,
        position=position,
        n_folds=n_folds,
        random_state=random_state,
    )
    q_hat = np.asarray(q_hat, dtype=float)
    expected_shape = (len(context), int(feedback["n_actions"]), int(action_dist.shape[1]))
    if q_hat.shape != expected_shape:
        raise ValueError(f"unexpected RF q_hat shape: {q_hat.shape} != {expected_shape}")
    if not np.isfinite(q_hat).all():
        raise ValueError("RF q_hat must be finite before calibration")
    calibration_shift = float(reward.mean() - q_hat.mean())
    q_hat = q_hat + calibration_shift
    if not np.isfinite(q_hat).all():
        raise ValueError("RF q_hat must remain finite after calibration")
    return q_hat, calibration_shift


def build_rf_rows(
    baseline_rows: Sequence[LoggedBanditRecord],
    feedback: Mapping[str, Any],
    action_dist: Any,
    q_hat: Any,
) -> tuple[LoggedBanditRecord, ...]:
    import numpy as np

    action = np.asarray(feedback["action"], dtype=int)
    position = _position_array(feedback)
    rows: list[LoggedBanditRecord] = []
    for index, baseline in enumerate(baseline_rows):
        pos = int(position[index])
        logged_action = int(action[index])
        baseline_q = float(q_hat[index, logged_action, pos])
        target_q = float(np.dot(action_dist[:, pos], q_hat[index, :, pos]))
        if not isfinite(baseline_q) or not isfinite(target_q):
            raise ValueError("RF factual and target Q terms must be finite")
        rows.append(
            LoggedBanditRecord(
                reward=baseline.reward,
                behavior_propensity=baseline.behavior_propensity,
                target_action_probability=baseline.target_action_probability,
                baseline_q=baseline_q,
                target_q=target_q,
                cluster_id=baseline.cluster_id,
                record_id=baseline.record_id,
            )
        )
    return tuple(rows)


def _summary(value: float, standard_error: float, reference: float) -> dict[str, float]:
    return {
        "estimate": float(value),
        "absolute_error": abs(float(value) - reference),
        "standard_error": float(standard_error),
    }


def candidate_grid(rows: Sequence[LoggedBanditRecord], *, reference: float) -> dict[str, dict[str, float]]:
    base = evaluate_policy(rows, switch_threshold=5.0, dr_os_lambda=1.0, beta_folds=5)
    switch_10 = evaluate_policy(rows, switch_threshold=10.0, beta_folds=5)
    dros_10 = evaluate_policy(rows, dr_os_lambda=10.0, beta_folds=5)
    return {
        "beta-cf5": _summary(base.beta_ips, base.beta_ips_standard_error, reference),
        "dr": _summary(base.doubly_robust, base.dr_standard_error, reference),
        "ips": _summary(base.ips, base.ips_standard_error, reference),
        "snips": _summary(base.self_normalized_ips, base.snips_standard_error, reference),
        "switch-5": _summary(base.switch_dr, base.switch_dr_standard_error, reference),
        "switch-10": _summary(switch_10.switch_dr, switch_10.switch_dr_standard_error, reference),
        "dros-1": _summary(base.dr_os, base.dr_os_standard_error, reference),
        "dros-10": _summary(dros_10.dr_os, dros_10.dr_os_standard_error, reference),
        "meta-blue": _summary(base.meta_blue, base.meta_blue_standard_error, reference),
    }


def _winner(grid: Mapping[str, Mapping[str, float]]) -> tuple[str, Mapping[str, float]]:
    return min(
        grid.items(),
        key=lambda item: (
            item[1]["absolute_error"],
            item[1]["standard_error"],
            item[0],
        ),
    )


def compare_q_backends(
    *,
    baseline_validation_jsonl: str | Path,
    data_path: str | Path,
    campaign: str,
    reference: float,
    n_sim: int,
    random_state: int,
) -> dict[str, Any]:
    if campaign not in {"all", "men", "women"}:
        raise ValueError("campaign must be one of all, men, women")
    if not isfinite(reference):
        raise ValueError("reference must be finite")
    if n_sim <= 0:
        raise ValueError("n_sim must be positive")
    if random_state != _RF_RANDOM_STATE:
        raise ValueError("development RF protocol fixes random_state=12345")

    import numpy as np
    from obp.dataset import OpenBanditDataset

    baseline_rows = load_logged_rows(baseline_validation_jsonl)
    dataset = OpenBanditDataset(
        behavior_policy="random",
        campaign=campaign,
        data_path=Path(data_path),
    )
    full_feedback = dataset.obtain_batch_bandit_feedback()
    feedback = _slice_feedback(full_feedback, len(baseline_rows))
    action_dist = _shared_bts_action_dist(
        dataset,
        campaign=campaign,
        n_sim=n_sim,
        random_state=random_state,
    )
    _validate_fixed_logged_evidence(baseline_rows, feedback, action_dist)

    q_hat, calibration_shift = fit_author_random_forest_q(
        feedback,
        action_dist=action_dist,
        random_state=random_state,
        n_folds=_RF_FOLDS,
    )
    rf_rows = build_rf_rows(baseline_rows, feedback, action_dist, q_hat)

    logistic_grid = candidate_grid(baseline_rows, reference=reference)
    rf_grid = candidate_grid(rf_rows, reference=reference)
    logistic_winner_name, logistic_winner = _winner(logistic_grid)
    rf_winner_name, rf_winner = _winner(rf_grid)

    q_min = float(np.min(q_hat))
    q_max = float(np.max(q_hat))
    return {
        "schema_version": "growthevo.obd-q-backend-development.v1",
        "sample_size": len(baseline_rows),
        "reference_value": float(reference),
        "campaign": campaign,
        "n_sim": n_sim,
        "random_state": random_state,
        "fixed_logged_evidence_verified": True,
        "logistic": {
            "q_model": "logistic",
            "q_folds": 2,
            "winner": logistic_winner_name,
            "winner_absolute_error": logistic_winner["absolute_error"],
            "winner_standard_error": logistic_winner["standard_error"],
            "grid": logistic_grid,
        },
        "random_forest": {
            "q_model": "random_forest",
            "q_folds": _RF_FOLDS,
            "n_estimators": _RF_TREES,
            "max_depth": _RF_MAX_DEPTH,
            "n_jobs": -1,
            "mean_calibration": True,
            "calibration_shift": calibration_shift,
            "q_hat_min": q_min,
            "q_hat_max": q_max,
            "winner": rf_winner_name,
            "winner_absolute_error": rf_winner["absolute_error"],
            "winner_standard_error": rf_winner["standard_error"],
            "grid": rf_grid,
        },
        "absolute_error_change_vs_logistic_winner": (
            rf_winner["absolute_error"] - logistic_winner["absolute_error"]
        ),
        "beats_logistic_winner": rf_winner["absolute_error"] < logistic_winner["absolute_error"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare fixed logistic Q against author-faithful RF Q on OBD validation only."
    )
    parser.add_argument("--baseline-validation-jsonl", required=True)
    parser.add_argument("--data-path", required=True)
    parser.add_argument("--campaign", choices=["all", "men", "women"], default="all")
    parser.add_argument("--reference", type=float, required=True)
    parser.add_argument("--n-sim", type=int, default=500)
    parser.add_argument("--random-state", type=int, default=12345)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    result = compare_q_backends(
        baseline_validation_jsonl=args.baseline_validation_jsonl,
        data_path=args.data_path,
        campaign=args.campaign,
        reference=args.reference,
        n_sim=args.n_sim,
        random_state=args.random_state,
    )
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
