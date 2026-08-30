from __future__ import annotations

"""Validation-only comparison of normal-logistic Q and MRDR-logistic Q.

The logged data, evaluation-policy probabilities, LogisticRegression model class,
cross-fitting folds, and random seed stay fixed.  The only statistical change is
OBP RegressionModel(fitting_method="mrdr"), which trains the reward model with
weights designed to reduce the variance of the doubly robust estimator.

This development comparator never consumes holdout evidence and is intentionally
not part of GrowthEvo's locked estimator or experiment-plan registry.
"""

import argparse
import json
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from growthevo.rl.ope import LoggedBanditRecord, evaluate_policy


_Q_FOLDS = 2
_RANDOM_STATE = 12345
_LOGISTIC_C = 1.0
_LOGISTIC_MAX_ITER = 1000


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


def fit_mrdr_logistic_q(
    feedback: Mapping[str, Any],
    *,
    action_dist: Any,
    random_state: int = _RANDOM_STATE,
    n_folds: int = _Q_FOLDS,
) -> tuple[Any, dict[str, float]]:
    """Fit 2-fold logistic Q with the OBP MRDR sample-weight objective."""

    import numpy as np
    from obp.ope import RegressionModel
    from sklearn.linear_model import LogisticRegression

    if n_folds != _Q_FOLDS:
        raise ValueError("development protocol fixes Q cross-fitting at 2 folds")
    if random_state != _RANDOM_STATE:
        raise ValueError("development protocol fixes random_state=12345")

    context = np.asarray(feedback["context"])
    action = np.asarray(feedback["action"], dtype=int)
    reward = np.asarray(feedback["reward"], dtype=float)
    pscore = np.asarray(feedback["pscore"], dtype=float)
    position = _position_array(feedback)
    n_rounds = len(context)
    n_actions = int(feedback["n_actions"])
    len_list = int(action_dist.shape[1])

    full_action_dist = np.broadcast_to(
        np.asarray(action_dist, dtype=float),
        (n_rounds, n_actions, len_list),
    )
    model = RegressionModel(
        n_actions=n_actions,
        len_list=len_list,
        action_context=feedback["action_context"],
        fitting_method="mrdr",
        base_model=LogisticRegression(
            C=_LOGISTIC_C,
            max_iter=_LOGISTIC_MAX_ITER,
            random_state=random_state,
        ),
    )
    q_hat = model.fit_predict(
        context=context,
        action=action,
        reward=reward,
        pscore=pscore,
        position=position,
        action_dist=full_action_dist,
        n_folds=n_folds,
        random_state=random_state,
    )
    q_hat = np.asarray(q_hat, dtype=float)
    expected_shape = (n_rounds, n_actions, len_list)
    if q_hat.shape != expected_shape:
        raise ValueError(f"unexpected MRDR q_hat shape: {q_hat.shape} != {expected_shape}")
    if not np.isfinite(q_hat).all():
        raise ValueError("MRDR q_hat must be finite")

    factual_target_probability = full_action_dist[
        np.arange(n_rounds), action, position
    ]
    mrdr_weights = (
        factual_target_probability * (1.0 - pscore) / (pscore * pscore)
    )
    if not np.isfinite(mrdr_weights).all() or np.any(mrdr_weights < 0.0):
        raise ValueError("MRDR sample weights must be finite and non-negative")
    diagnostics = {
        "sample_weight_min": float(np.min(mrdr_weights)),
        "sample_weight_mean": float(np.mean(mrdr_weights)),
        "sample_weight_max": float(np.max(mrdr_weights)),
        "q_hat_min": float(np.min(q_hat)),
        "q_hat_max": float(np.max(q_hat)),
    }
    return q_hat, diagnostics


def build_q_rows(
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
            raise ValueError("MRDR factual and target Q terms must be finite")
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


def compare_q_objectives(
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
    if random_state != _RANDOM_STATE:
        raise ValueError("development protocol fixes random_state=12345")

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

    q_hat, diagnostics = fit_mrdr_logistic_q(
        feedback,
        action_dist=action_dist,
        random_state=random_state,
        n_folds=_Q_FOLDS,
    )
    mrdr_rows = build_q_rows(baseline_rows, feedback, action_dist, q_hat)

    normal_grid = candidate_grid(baseline_rows, reference=reference)
    mrdr_grid = candidate_grid(mrdr_rows, reference=reference)
    normal_winner_name, normal_winner = _winner(normal_grid)
    mrdr_winner_name, mrdr_winner = _winner(mrdr_grid)

    return {
        "schema_version": "growthevo.obd-mrdr-q-development.v1",
        "sample_size": len(baseline_rows),
        "reference_value": float(reference),
        "campaign": campaign,
        "n_sim": n_sim,
        "random_state": random_state,
        "fixed_logged_evidence_verified": True,
        "normal_logistic": {
            "q_model": "logistic",
            "q_folds": _Q_FOLDS,
            "fitting_method": "normal",
            "winner": normal_winner_name,
            "winner_absolute_error": normal_winner["absolute_error"],
            "winner_standard_error": normal_winner["standard_error"],
            "grid": normal_grid,
        },
        "mrdr_logistic": {
            "q_model": "logistic",
            "q_folds": _Q_FOLDS,
            "fitting_method": "mrdr",
            "logistic_c": _LOGISTIC_C,
            "logistic_max_iter": _LOGISTIC_MAX_ITER,
            **diagnostics,
            "winner": mrdr_winner_name,
            "winner_absolute_error": mrdr_winner["absolute_error"],
            "winner_standard_error": mrdr_winner["standard_error"],
            "grid": mrdr_grid,
        },
        "absolute_error_change_vs_normal_winner": (
            mrdr_winner["absolute_error"] - normal_winner["absolute_error"]
        ),
        "beats_normal_winner": mrdr_winner["absolute_error"] < normal_winner["absolute_error"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare normal and MRDR logistic Q on fixed OBD validation evidence."
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
    result = compare_q_objectives(
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
