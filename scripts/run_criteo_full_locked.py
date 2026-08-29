from __future__ import annotations

"""Run the preregistered full Criteo v2.1 randomized-targeting benchmark.

The runner deliberately separates train, validation selection, and final holdout.
All candidate models are fit only on the predeclared training split. Validation
scores for every candidate are then evaluated on randomized evidence to freeze a
single winner. Only that winner is scored on the final holdout.

The public Criteo file is pinned by repository commit and SHA256. ``exposure`` is
post-assignment and is never loaded as a feature or treatment variable.
"""

import argparse
from dataclasses import asdict
from hashlib import blake2b, sha256
import json
from math import isfinite, sqrt
from pathlib import Path
import shutil
import subprocess
import sys
from statistics import NormalDist
from typing import Any, Mapping, Sequence
import urllib.request

from growthevo.bench.locked_evaluation import LockedBenchmarkArtifact
from growthevo.bench.targeting_experiment_plan import load_targeting_experiment_plan


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PLAN = _REPO_ROOT / "benchmarks" / "targeting" / "criteo-v2.1-visit-top10.v1.json"
_DEFAULT_CANDIDATES = _REPO_ROOT / "benchmarks" / "targeting" / "criteo-lgbm-candidates.v1.json"
_SOURCE_COMMIT = "82811785048bb633de2d55c02bab4e57066e6423"
_SOURCE_FILE = "criteo-research-uplift-v2.1.csv.gz"
_SOURCE_URL = (
    "https://huggingface.co/datasets/criteo/criteo-uplift/resolve/"
    f"{_SOURCE_COMMIT}/{_SOURCE_FILE}?download=true"
)
_SOURCE_SHA256 = "2716e1bf0fd157a93b5bf86924d9088419dfbac2022c6cd90030220634f616dc"
_EXPECTED_ROWS = 13_979_592
_EXPECTED_SOURCE_BYTES = 311_422_618
_MASK64 = (1 << 64) - 1
_SPLITMIX_GAMMA = 0x9E3779B97F4A7C15
_SPLITMIX_M1 = 0xBF58476D1CE4E5B9
_SPLITMIX_M2 = 0x94D049BB133111EB


def _canonical_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return blake2b(encoded, digest_size=20).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=_REPO_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown-local-commit"


def _splitmix64_value(index: int, seed: int) -> int:
    value = (int(index) + int(seed) + _SPLITMIX_GAMMA) & _MASK64
    value = ((value ^ (value >> 30)) * _SPLITMIX_M1) & _MASK64
    value = ((value ^ (value >> 27)) * _SPLITMIX_M2) & _MASK64
    return (value ^ (value >> 31)) & _MASK64


def _split_label_value(
    index: int,
    *,
    seed: int,
    training_fraction: float,
    validation_fraction: float,
) -> int:
    value = _splitmix64_value(index, seed)
    train_cut = int(training_fraction * (1 << 64))
    validation_cut = int((training_fraction + validation_fraction) * (1 << 64))
    if value < train_cut:
        return 0
    if value < validation_cut:
        return 1
    return 2


def _split_labels_np(
    indices: Any,
    *,
    seed: int,
    training_fraction: float,
    validation_fraction: float,
) -> Any:
    import numpy as np

    values = np.asarray(indices, dtype=np.uint64)
    with np.errstate(over="ignore"):
        values = values + np.uint64(seed) + np.uint64(_SPLITMIX_GAMMA)
        values = (values ^ (values >> np.uint64(30))) * np.uint64(_SPLITMIX_M1)
        values = (values ^ (values >> np.uint64(27))) * np.uint64(_SPLITMIX_M2)
        values = values ^ (values >> np.uint64(31))
    train_cut = np.uint64(int(training_fraction * (1 << 64)))
    validation_cut = np.uint64(
        int((training_fraction + validation_fraction) * (1 << 64))
    )
    labels = np.full(values.shape, 2, dtype=np.uint8)
    labels[values < validation_cut] = 1
    labels[values < train_cut] = 0
    return labels


def _split_counts(
    n_rows: int,
    *,
    seed: int,
    training_fraction: float,
    validation_fraction: float,
    batch_size: int = 1_000_000,
) -> tuple[int, int, int]:
    import numpy as np

    counts = np.zeros(3, dtype=np.int64)
    for start in range(0, n_rows, batch_size):
        stop = min(n_rows, start + batch_size)
        labels = _split_labels_np(
            np.arange(start, stop, dtype=np.uint64),
            seed=seed,
            training_fraction=training_fraction,
            validation_fraction=validation_fraction,
        )
        counts += np.bincount(labels, minlength=3)
    result = tuple(int(value) for value in counts)
    if sum(result) != n_rows or any(value <= 0 for value in result):
        raise RuntimeError("predeclared Criteo split produced an invalid cohort size")
    return result


def _download_source(cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / _SOURCE_FILE
    if destination.is_file():
        digest = _sha256_file(destination)
        if digest == _SOURCE_SHA256:
            return destination
        destination.unlink()

    partial = destination.with_suffix(destination.suffix + ".partial")
    if partial.exists():
        partial.unlink()
    request = urllib.request.Request(
        _SOURCE_URL,
        headers={"User-Agent": "GrowthEvo-Harness/full-criteo-benchmark"},
    )
    with urllib.request.urlopen(request) as response, partial.open("wb") as output:
        shutil.copyfileobj(response, output, length=8 * 1024 * 1024)
    digest = _sha256_file(partial)
    if digest != _SOURCE_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            f"pinned Criteo SHA256 mismatch: observed={digest}, expected={_SOURCE_SHA256}"
        )
    partial.replace(destination)
    return destination


def _load_candidate_config(path: Path) -> tuple[dict[str, Any], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Criteo candidate config must be a JSON object")
    fingerprint = _canonical_fingerprint(payload)
    if payload.get("schema_version") != "growthevo.criteo-cate-candidates.v1":
        raise ValueError("unsupported Criteo candidate config schema")
    if payload.get("lightgbm_version") != "4.7.0":
        raise ValueError("Criteo candidate config must pin LightGBM 4.7.0")
    features = payload.get("feature_columns")
    if features != [f"f{index}" for index in range(12)]:
        raise ValueError("Criteo candidate config must use exactly f0..f11")
    if "exposure" not in payload.get("forbidden_columns", []):
        raise ValueError("Criteo candidate config must explicitly forbid exposure")
    if payload.get("nuisance_folds") != 2:
        raise ValueError("Criteo candidate config currently requires two nuisance folds")
    if isinstance(payload.get("nuisance_fold_seed_offset"), bool) or not isinstance(
        payload.get("nuisance_fold_seed_offset"), int
    ):
        raise ValueError("Criteo nuisance fold seed offset must be an integer")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Criteo candidate config requires candidate definitions")
    names = [candidate.get("name") for candidate in candidates if isinstance(candidate, dict)]
    if len(names) != len(candidates) or any(not isinstance(name, str) or not name for name in names):
        raise ValueError("Criteo candidate definitions require non-empty names")
    if len(set(names)) != len(names):
        raise ValueError("Criteo candidate names must be unique")
    return payload, fingerprint


def _load_train_validation(
    source: Path,
    *,
    feature_names: Sequence[str],
    outcome_name: str,
    n_rows: int,
    seed: int,
    training_fraction: float,
    validation_fraction: float,
    chunk_size: int,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    import numpy as np
    import pandas as pd

    train_n, validation_n, _ = _split_counts(
        n_rows,
        seed=seed,
        training_fraction=training_fraction,
        validation_fraction=validation_fraction,
    )
    width = len(feature_names)
    train = {
        "x": np.empty((train_n, width), dtype=np.float32),
        "t": np.empty(train_n, dtype=np.uint8),
        "y": np.empty(train_n, dtype=np.uint8),
        "source_index": np.empty(train_n, dtype=np.uint64),
    }
    validation = {
        "x": np.empty((validation_n, width), dtype=np.float32),
        "t": np.empty(validation_n, dtype=np.uint8),
        "y": np.empty(validation_n, dtype=np.uint8),
        "source_index": np.empty(validation_n, dtype=np.uint64),
    }
    train_cursor = 0
    validation_cursor = 0
    row_start = 0
    usecols = [*feature_names, "treatment", outcome_name]
    dtypes = {name: "float32" for name in feature_names}
    dtypes.update({"treatment": "uint8", outcome_name: "uint8"})
    for chunk in pd.read_csv(
        source,
        compression="gzip",
        usecols=usecols,
        dtype=dtypes,
        chunksize=chunk_size,
    ):
        chunk_n = int(chunk.shape[0])
        indices = np.arange(row_start, row_start + chunk_n, dtype=np.uint64)
        labels = _split_labels_np(
            indices,
            seed=seed,
            training_fraction=training_fraction,
            validation_fraction=validation_fraction,
        )
        features = chunk[list(feature_names)].to_numpy(dtype=np.float32, copy=False)
        treatment = chunk["treatment"].to_numpy(dtype=np.uint8, copy=False)
        outcome = chunk[outcome_name].to_numpy(dtype=np.uint8, copy=False)
        if not np.isfinite(features).all():
            raise ValueError("Criteo features must be finite")
        if not np.isin(treatment, [0, 1]).all():
            raise ValueError("Criteo treatment must be binary")
        if not np.isin(outcome, [0, 1]).all():
            raise ValueError(f"Criteo {outcome_name} must be binary")

        for label, cohort, cursor_name in (
            (0, train, "train"),
            (1, validation, "validation"),
        ):
            mask = labels == label
            count = int(mask.sum())
            if not count:
                continue
            cursor = train_cursor if cursor_name == "train" else validation_cursor
            stop = cursor + count
            cohort["x"][cursor:stop] = features[mask]
            cohort["t"][cursor:stop] = treatment[mask]
            cohort["y"][cursor:stop] = outcome[mask]
            cohort["source_index"][cursor:stop] = indices[mask]
            if cursor_name == "train":
                train_cursor = stop
            else:
                validation_cursor = stop
        row_start += chunk_n

    if row_start != n_rows:
        raise RuntimeError(f"Criteo row-count drift: observed={row_start}, expected={n_rows}")
    if train_cursor != train_n or validation_cursor != validation_n:
        raise RuntimeError("Criteo train/validation materialization count drift")
    return train, validation, row_start


def _load_holdout(
    source: Path,
    *,
    feature_names: Sequence[str],
    outcome_name: str,
    n_rows: int,
    seed: int,
    training_fraction: float,
    validation_fraction: float,
    chunk_size: int,
) -> dict[str, Any]:
    import numpy as np
    import pandas as pd

    _, _, holdout_n = _split_counts(
        n_rows,
        seed=seed,
        training_fraction=training_fraction,
        validation_fraction=validation_fraction,
    )
    width = len(feature_names)
    holdout = {
        "x": np.empty((holdout_n, width), dtype=np.float32),
        "t": np.empty(holdout_n, dtype=np.uint8),
        "y": np.empty(holdout_n, dtype=np.uint8),
        "source_index": np.empty(holdout_n, dtype=np.uint64),
    }
    cursor = 0
    row_start = 0
    usecols = [*feature_names, "treatment", outcome_name]
    dtypes = {name: "float32" for name in feature_names}
    dtypes.update({"treatment": "uint8", outcome_name: "uint8"})
    for chunk in pd.read_csv(
        source,
        compression="gzip",
        usecols=usecols,
        dtype=dtypes,
        chunksize=chunk_size,
    ):
        chunk_n = int(chunk.shape[0])
        indices = np.arange(row_start, row_start + chunk_n, dtype=np.uint64)
        labels = _split_labels_np(
            indices,
            seed=seed,
            training_fraction=training_fraction,
            validation_fraction=validation_fraction,
        )
        mask = labels == 2
        count = int(mask.sum())
        if count:
            stop = cursor + count
            features = chunk[list(feature_names)].to_numpy(dtype=np.float32, copy=False)
            treatment = chunk["treatment"].to_numpy(dtype=np.uint8, copy=False)
            outcome = chunk[outcome_name].to_numpy(dtype=np.uint8, copy=False)
            if not np.isfinite(features[mask]).all():
                raise ValueError("Criteo holdout features must be finite")
            if not np.isin(treatment[mask], [0, 1]).all():
                raise ValueError("Criteo holdout treatment must be binary")
            if not np.isin(outcome[mask], [0, 1]).all():
                raise ValueError(f"Criteo holdout {outcome_name} must be binary")
            holdout["x"][cursor:stop] = features[mask]
            holdout["t"][cursor:stop] = treatment[mask]
            holdout["y"][cursor:stop] = outcome[mask]
            holdout["source_index"][cursor:stop] = indices[mask]
            cursor = stop
        row_start += chunk_n
    if row_start != n_rows or cursor != holdout_n:
        raise RuntimeError("Criteo holdout materialization count drift")
    return holdout


def _fold_labels(source_indices: Any, *, seed: int, folds: int) -> Any:
    import numpy as np

    if folds < 2:
        raise ValueError("nuisance folds must be at least two")
    values = np.asarray(source_indices, dtype=np.uint64)
    with np.errstate(over="ignore"):
        values = values + np.uint64(seed) + np.uint64(_SPLITMIX_GAMMA)
        values = (values ^ (values >> np.uint64(30))) * np.uint64(_SPLITMIX_M1)
        values = (values ^ (values >> np.uint64(27))) * np.uint64(_SPLITMIX_M2)
        values = values ^ (values >> np.uint64(31))
    return (values % np.uint64(folds)).astype(np.uint8)


def _classifier(params: Mapping[str, Any]) -> Any:
    from lightgbm import LGBMClassifier

    return LGBMClassifier(**dict(params))


def _regressor(params: Mapping[str, Any]) -> Any:
    from lightgbm import LGBMRegressor

    return LGBMRegressor(**dict(params))


def _fit_outcome_nuisance(
    train: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    split_seed: int,
) -> tuple[Any, Any, Any, Any]:
    import gc
    import numpy as np

    x = train["x"]
    t = train["t"]
    y = train["y"]
    n = len(y)
    folds = int(config["nuisance_folds"])
    fold_seed = split_seed + int(config["nuisance_fold_seed_offset"])
    labels = _fold_labels(train["source_index"], seed=fold_seed, folds=folds)
    mu0_oof = np.empty(n, dtype=np.float32)
    mu1_oof = np.empty(n, dtype=np.float32)
    params = config["common_classifier"]

    for fold in range(folds):
        held = labels == fold
        fit = ~held
        for arm, destination in ((0, mu0_oof), (1, mu1_oof)):
            arm_fit = fit & (t == arm)
            target = y[arm_fit]
            if target.size == 0 or np.unique(target).size != 2:
                raise RuntimeError("Criteo nuisance fold/arm must contain both outcome classes")
            model = _classifier(params)
            model.fit(x[arm_fit], target)
            destination[held] = model.predict_proba(x[held])[:, 1].astype(np.float32)
            del model, arm_fit, target
            gc.collect()

    if not np.isfinite(mu0_oof).all() or not np.isfinite(mu1_oof).all():
        raise RuntimeError("Criteo OOF nuisance predictions must be finite")

    full_models: list[Any] = []
    for arm in (0, 1):
        arm_mask = t == arm
        target = y[arm_mask]
        if target.size == 0 or np.unique(target).size != 2:
            raise RuntimeError("Criteo training arm must contain both outcome classes")
        model = _classifier(params)
        model.fit(x[arm_mask], target)
        full_models.append(model)
        del arm_mask, target
        gc.collect()
    return mu0_oof, mu1_oof, full_models[0], full_models[1]


def _fit_candidate_models(
    train: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    propensity: float,
    split_seed: int,
) -> dict[str, Any]:
    import gc
    import numpy as np

    if not 0.0 < propensity < 1.0:
        raise ValueError("training propensity must be in (0, 1)")
    x = train["x"]
    t = train["t"]
    y = train["y"].astype(np.float32, copy=False)
    mu0_oof, mu1_oof, mu0_full, mu1_full = _fit_outcome_nuisance(
        train,
        config=config,
        split_seed=split_seed,
    )
    models: dict[str, Any] = {"t-lgbm": (mu0_full, mu1_full)}

    # S-learner: treatment is the only added feature; exposure is never loaded.
    augmented = np.empty((x.shape[0], x.shape[1] + 1), dtype=np.float32)
    augmented[:, :-1] = x
    augmented[:, -1] = t
    s_model = _classifier(config["common_classifier"])
    s_model.fit(augmented, y)
    models["s-lgbm"] = s_model
    del augmented, s_model
    gc.collect()

    # X-learner: OOF counterfactual imputation followed by arm-specific effect models.
    x_pseudo = np.where(t == 1, y - mu0_oof, mu1_oof - y).astype(np.float32)
    x_models: list[Any] = []
    for arm in (0, 1):
        arm_mask = t == arm
        model = _regressor(config["common_regressor"])
        model.fit(x[arm_mask], x_pseudo[arm_mask])
        x_models.append(model)
        del arm_mask, model
        gc.collect()
    models["x-lgbm"] = (x_models[0], x_models[1])
    del x_pseudo, x_models

    # DR-learner: cross-fitted AIPW pseudo-outcome.
    dr_pseudo = (
        mu1_oof
        - mu0_oof
        + t * (y - mu1_oof) / propensity
        - (1.0 - t) * (y - mu0_oof) / (1.0 - propensity)
    ).astype(np.float32)
    dr_model = _regressor(config["common_regressor"])
    dr_model.fit(x, dr_pseudo)
    models["dr-lgbm"] = dr_model
    del dr_pseudo, dr_model
    gc.collect()

    # R-learner: Robinson residualization represented as a weighted pseudo-outcome.
    marginal_oof = (propensity * mu1_oof + (1.0 - propensity) * mu0_oof).astype(
        np.float32
    )
    treatment_residual = t.astype(np.float32) - np.float32(propensity)
    if np.any(np.abs(treatment_residual) < 1e-8):
        raise RuntimeError("R-learner treatment residual unexpectedly approaches zero")
    r_pseudo = ((y - marginal_oof) / treatment_residual).astype(np.float32)
    r_weight = (treatment_residual * treatment_residual).astype(np.float32)
    r_model = _regressor(config["common_regressor"])
    r_model.fit(x, r_pseudo, sample_weight=r_weight)
    models["r-lgbm"] = r_model
    del marginal_oof, treatment_residual, r_pseudo, r_weight, r_model
    del mu0_oof, mu1_oof
    gc.collect()
    return models


def _predict_candidate(
    name: str,
    models: Mapping[str, Any],
    x: Any,
    *,
    propensity: float,
    batch_size: int,
) -> Any:
    import numpy as np

    if batch_size <= 0:
        raise ValueError("prediction batch size must be positive")
    scores = np.empty(x.shape[0], dtype=np.float32)
    for start in range(0, x.shape[0], batch_size):
        stop = min(x.shape[0], start + batch_size)
        batch = x[start:stop]
        if name == "s-lgbm":
            model = models[name]
            augmented = np.empty((batch.shape[0], batch.shape[1] + 1), dtype=np.float32)
            augmented[:, :-1] = batch
            augmented[:, -1] = 1.0
            treated = model.predict_proba(augmented)[:, 1]
            augmented[:, -1] = 0.0
            control = model.predict_proba(augmented)[:, 1]
            values = treated - control
        elif name == "t-lgbm":
            mu0, mu1 = models[name]
            values = mu1.predict_proba(batch)[:, 1] - mu0.predict_proba(batch)[:, 1]
        elif name == "x-lgbm":
            tau0, tau1 = models[name]
            values = propensity * tau0.predict(batch) + (1.0 - propensity) * tau1.predict(batch)
        elif name in {"r-lgbm", "dr-lgbm"}:
            values = models[name].predict(batch)
        else:
            raise ValueError(f"unsupported Criteo candidate: {name}")
        scores[start:stop] = np.asarray(values, dtype=np.float32)
    if not np.isfinite(scores).all():
        raise RuntimeError(f"Criteo candidate {name} produced non-finite scores")
    return scores


def _top_k_mask(scores: Any, source_indices: Any, selected_fraction: float) -> Any:
    import numpy as np

    values = np.asarray(scores, dtype=np.float32)
    indices = np.asarray(source_indices, dtype=np.uint64)
    n = values.size
    if n == 0 or indices.size != n:
        raise ValueError("top-k scores and source indices must be non-empty and aligned")
    if not np.isfinite(values).all():
        raise ValueError("top-k scores must be finite")
    if not 0.0 < selected_fraction <= 1.0:
        raise ValueError("selected_fraction must be in (0, 1]")
    k = max(1, int(round(n * selected_fraction)))
    if k >= n:
        return np.ones(n, dtype=bool)
    threshold = np.partition(values, n - k)[n - k]
    selected = values > threshold
    remaining = k - int(selected.sum())
    if remaining < 0:
        raise RuntimeError("top-k threshold selected more rows than requested")
    if remaining:
        tied = np.flatnonzero(values == threshold)
        order = np.argsort(indices[tied], kind="stable")
        selected[tied[order[:remaining]]] = True
    if int(selected.sum()) != k:
        raise RuntimeError("deterministic top-k selection count drift")
    return selected


def _evaluate_vectorized_targeting(
    cohort: Mapping[str, Any],
    scores: Any,
    *,
    propensity: float,
    selected_fraction: float,
    confidence_level: float = 0.95,
) -> dict[str, float | int]:
    import numpy as np

    if not 0.0 < propensity < 1.0:
        raise ValueError("targeting propensity must be in (0, 1)")
    t = np.asarray(cohort["t"], dtype=np.uint8)
    y = np.asarray(cohort["y"], dtype=np.float64)
    source_indices = cohort["source_index"]
    if t.size < 2 or y.size != t.size:
        raise ValueError("targeting cohort must contain at least two aligned rows")
    selected = _top_k_mask(scores, source_indices, selected_fraction)
    treated = t == 1
    control = ~treated
    n = t.size
    treat_none_sum = float(y[control].sum()) / (1.0 - propensity)
    treat_all_sum = float(y[treated].sum()) / propensity
    policy_sum = (
        float(y[selected & treated].sum()) / propensity
        + float(y[(~selected) & control].sum()) / (1.0 - propensity)
    )
    treat_none_value = treat_none_sum / n
    treat_all_value = treat_all_sum / n
    policy_value = policy_sum / n
    incremental = policy_value - treat_none_value

    selected_treated_sum = float(y[selected & treated].sum()) / propensity
    selected_control_sum = -float(y[selected & control].sum()) / (1.0 - propensity)
    term_sum = selected_treated_sum + selected_control_sum
    term_sq_sum = (
        float(y[selected & treated].sum()) / (propensity * propensity)
        + float(y[selected & control].sum()) / ((1.0 - propensity) ** 2)
    )
    mean = term_sum / n
    if abs(mean - incremental) > 1e-12:
        raise RuntimeError("vectorized targeting influence terms disagree with policy value")
    variance_numerator = max(0.0, term_sq_sum - n * mean * mean)
    sample_variance = variance_numerator / (n - 1)
    standard_error = sqrt(sample_variance / n)
    alpha = 1.0 - confidence_level
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    realized_fraction = float(selected.sum()) / n
    selected_incremental = incremental / realized_fraction
    selected_se = standard_error / realized_fraction
    return {
        "sample_size": int(n),
        "selected_fraction": realized_fraction,
        "policy_value": policy_value,
        "treat_none_value": treat_none_value,
        "treat_all_value": treat_all_value,
        "incremental_value_vs_none": incremental,
        "standard_error": standard_error,
        "confidence_level": confidence_level,
        "lower_incremental_value": incremental - z * standard_error,
        "upper_incremental_value": incremental + z * standard_error,
        "selected_incremental_value": selected_incremental,
        "selected_standard_error": selected_se,
        "lower_selected_incremental_value": selected_incremental - z * selected_se,
        "upper_selected_incremental_value": selected_incremental + z * selected_se,
    }


def _array_bytes(array: Any, dtype: str) -> bytes:
    import numpy as np

    return np.asarray(array, dtype=np.dtype(dtype)).tobytes(order="C")


def _targeting_fingerprint(
    cohort: Mapping[str, Any],
    candidate_scores: Mapping[str, Any],
    *,
    propensity: float,
    split_name: str,
) -> str:
    digest = blake2b(digest_size=20)
    digest.update(b"growthevo.criteo-vectorized-targeting-evidence.v1\n")
    digest.update(f"split:{split_name}\n".encode("utf-8"))
    digest.update(f"propensity:{float(propensity).hex()}\n".encode("utf-8"))
    digest.update(_array_bytes(cohort["source_index"], "<u8"))
    digest.update(_array_bytes(cohort["x"], "<f4"))
    digest.update(_array_bytes(cohort["t"], "u1"))
    digest.update(_array_bytes(cohort["y"], "u1"))
    for name in sorted(candidate_scores):
        digest.update(f"candidate:{name}\n".encode("utf-8"))
        digest.update(_array_bytes(candidate_scores[name], "<f4"))
    return digest.hexdigest()


def _manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    return _canonical_fingerprint(manifest)


def run_full_criteo(
    *,
    data_path: Path | None,
    cache_dir: Path,
    output_dir: Path,
    plan_path: Path,
    candidate_config_path: Path,
    chunk_size: int = 250_000,
    prediction_batch_size: int = 250_000,
) -> Path:
    import gc
    import lightgbm
    import numpy as np
    import pandas as pd
    import sklearn

    if chunk_size <= 0 or prediction_batch_size <= 0:
        raise ValueError("chunk and prediction batch sizes must be positive")
    plan = load_targeting_experiment_plan(plan_path)
    if plan.schema_version != "growthevo.targeting-experiment-plan.v2":
        raise ValueError("full Criteo runner requires targeting experiment plan v2")
    if plan.dataset != "criteo-uplift-v2.1" or plan.outcome_definition != "visit":
        raise ValueError("full Criteo runner requires the pinned v2.1 visit plan")
    if plan.training_fraction is None or plan.split_seed is None:
        raise ValueError("full Criteo plan is missing training split fields")

    config, config_fingerprint = _load_candidate_config(candidate_config_path)
    if config_fingerprint != plan.candidate_config_fingerprint:
        raise ValueError("candidate config fingerprint does not match pre-registered plan")
    config_names = tuple(candidate["name"] for candidate in config["candidates"])
    if set(config_names) != set(plan.candidate_names):
        raise ValueError("candidate config names do not match pre-registered plan")
    if lightgbm.__version__ != config["lightgbm_version"]:
        raise RuntimeError(
            f"LightGBM version drift: {lightgbm.__version__} != {config['lightgbm_version']}"
        )

    source = data_path.resolve() if data_path is not None else _download_source(cache_dir)
    observed_sha = _sha256_file(source)
    if observed_sha != _SOURCE_SHA256:
        raise RuntimeError("Criteo source SHA256 does not match pinned release")
    source_bytes = source.stat().st_size
    if source_bytes != _EXPECTED_SOURCE_BYTES:
        raise RuntimeError(
            f"Criteo source byte-size drift: {source_bytes} != {_EXPECTED_SOURCE_BYTES}"
        )

    feature_names = tuple(config["feature_columns"])
    train, validation, observed_rows = _load_train_validation(
        source,
        feature_names=feature_names,
        outcome_name=plan.outcome_definition,
        n_rows=_EXPECTED_ROWS,
        seed=plan.split_seed,
        training_fraction=plan.training_fraction,
        validation_fraction=plan.validation_fraction,
        chunk_size=chunk_size,
    )
    if observed_rows != _EXPECTED_ROWS:
        raise RuntimeError("Criteo observed row count does not match pinned release")
    propensity = float(np.mean(train["t"], dtype=np.float64))
    if not 0.0 < propensity < 1.0:
        raise RuntimeError("Criteo training split must contain treatment and control")

    models = _fit_candidate_models(
        train,
        config=config,
        propensity=propensity,
        split_seed=plan.split_seed,
    )
    validation_scores: dict[str, Any] = {}
    for name in plan.candidate_names:
        validation_scores[name] = _predict_candidate(
            name,
            models,
            validation["x"],
            propensity=propensity,
            batch_size=prediction_batch_size,
        )

    manifest: dict[str, Any] = {
        "schema_version": "growthevo.targeting-export.v2",
        "dataset_source": plan.dataset_source,
        "outcome_definition": plan.outcome_definition,
        "split_strategy": plan.split_strategy,
        "training_fraction": plan.training_fraction,
        "validation_fraction": plan.validation_fraction,
        "split_seed": plan.split_seed,
        "treatment": plan.treatment.value,
        "propensity_protocol": plan.propensity_protocol,
        "score_protocol": plan.score_protocol,
        "candidate_config_fingerprint": config_fingerprint,
        "candidate_names": list(plan.candidate_names),
        "source_rows": _EXPECTED_ROWS,
        "training_rows": int(len(train["t"])),
        "validation_rows": int(len(validation["t"])),
        "holdout_rows": int(_EXPECTED_ROWS - len(train["t"]) - len(validation["t"])),
        "training_treatment_share": propensity,
        "validation_treatment_share": float(np.mean(validation["t"], dtype=np.float64)),
        "lightgbm_version": lightgbm.__version__,
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "sklearn_version": sklearn.__version__,
        "source_sha256": observed_sha,
        "source_bytes": source_bytes,
        "source_commit": _SOURCE_COMMIT,
        "source_url": _SOURCE_URL,
        "forbidden_feature_columns": list(config["forbidden_columns"]),
        "holdout_score_policy": "winner-only-after-validation-freeze",
    }
    plan.validate_export_manifest(manifest)
    manifest_fingerprint = _manifest_fingerprint(manifest)

    validation_fingerprint = _targeting_fingerprint(
        validation,
        validation_scores,
        propensity=propensity,
        split_name="validation",
    )
    scoreboard: list[dict[str, Any]] = []
    for name in sorted(validation_scores):
        metrics = _evaluate_vectorized_targeting(
            validation,
            validation_scores[name],
            propensity=propensity,
            selected_fraction=plan.selected_fraction,
        )
        scoreboard.append({"candidate_name": name, **metrics})
    winner = max(
        scoreboard,
        key=lambda row: (
            row["incremental_value_vs_none"],
            row["policy_value"],
            row["candidate_name"],
        ),
    )["candidate_name"]

    # Validation is now frozen. Release all non-winning score vectors before the
    # second source pass; the holdout receives exactly one candidate prediction.
    validation_winner = next(row for row in scoreboard if row["candidate_name"] == winner)
    validation_scores.clear()
    del train, validation
    gc.collect()

    holdout = _load_holdout(
        source,
        feature_names=feature_names,
        outcome_name=plan.outcome_definition,
        n_rows=_EXPECTED_ROWS,
        seed=plan.split_seed,
        training_fraction=plan.training_fraction,
        validation_fraction=plan.validation_fraction,
        chunk_size=chunk_size,
    )
    holdout_score = _predict_candidate(
        winner,
        models,
        holdout["x"],
        propensity=propensity,
        batch_size=prediction_batch_size,
    )
    holdout_fingerprint = _targeting_fingerprint(
        holdout,
        {winner: holdout_score},
        propensity=propensity,
        split_name="holdout",
    )
    if holdout_fingerprint == validation_fingerprint:
        raise RuntimeError("Criteo validation and holdout evidence fingerprints must differ")
    holdout_metrics = _evaluate_vectorized_targeting(
        holdout,
        holdout_score,
        propensity=propensity,
        selected_fraction=plan.selected_fraction,
    )

    inner_protocol = _canonical_fingerprint(
        {
            "schema": "growthevo.criteo-vectorized-locked-targeting.v1",
            "selection_objective": "validation_incremental_value_vs_none",
            "selected_fraction": plan.selected_fraction,
            "treatment": plan.treatment.value,
            "fingerprint_schema": "growthevo.criteo-vectorized-targeting-evidence.v1",
        }
    )
    protocol_fingerprint = plan.bind_protocol_fingerprint(inner_protocol)
    artifact = LockedBenchmarkArtifact(
        benchmark=plan.benchmark,
        dataset=plan.dataset,
        commit_sha=_git_sha(),
        protocol_fingerprint=protocol_fingerprint,
        tuning_fingerprint=validation_fingerprint,
        test_fingerprint=holdout_fingerprint,
        selected_candidate=winner,
        metrics={
            "candidate_count": len(plan.candidate_names),
            "dataset_source": plan.dataset_source,
            "score_protocol": plan.score_protocol,
            "propensity_protocol": plan.propensity_protocol or "",
            "training_treatment_share": propensity,
            "validation_incremental_value_vs_none": validation_winner[
                "incremental_value_vs_none"
            ],
            "validation_selected_incremental_value": validation_winner[
                "selected_incremental_value"
            ],
            "sample_size": holdout_metrics["sample_size"],
            "selected_fraction": holdout_metrics["selected_fraction"],
            "policy_value": holdout_metrics["policy_value"],
            "treat_none_value": holdout_metrics["treat_none_value"],
            "treat_all_value": holdout_metrics["treat_all_value"],
            "incremental_value_vs_none": holdout_metrics[
                "incremental_value_vs_none"
            ],
            "standard_error": holdout_metrics["standard_error"],
            "confidence_level": holdout_metrics["confidence_level"],
            "lower_incremental_value": holdout_metrics["lower_incremental_value"],
            "upper_incremental_value": holdout_metrics["upper_incremental_value"],
            "selected_incremental_value": holdout_metrics["selected_incremental_value"],
            "selected_standard_error": holdout_metrics["selected_standard_error"],
            "lower_selected_incremental_value": holdout_metrics[
                "lower_selected_incremental_value"
            ],
            "upper_selected_incremental_value": holdout_metrics[
                "upper_selected_incremental_value"
            ],
            "experiment_plan_fingerprint": plan.fingerprint,
            "export_manifest_fingerprint": manifest_fingerprint,
            "candidate_config_fingerprint": config_fingerprint,
        },
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "export-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    shutil.copy2(plan_path, output_dir / plan_path.name)
    shutil.copy2(candidate_config_path, output_dir / candidate_config_path.name)
    source_provenance = {
        "source_url": _SOURCE_URL,
        "source_commit": _SOURCE_COMMIT,
        "source_sha256": observed_sha,
        "source_bytes": source_bytes,
        "license": "CC-BY-NC-SA-4.0",
        "growth_evo_commit_sha": _git_sha(),
        "experiment_plan_fingerprint": plan.fingerprint,
        "candidate_config_fingerprint": config_fingerprint,
    }
    (output_dir / "source-provenance.json").write_text(
        json.dumps(source_provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    result = {
        "schema_version": "growthevo.locked-targeting-run.v3",
        "experiment_plan": {
            "fingerprint": plan.fingerprint,
            "export_manifest_fingerprint": manifest_fingerprint,
            "plan": plan.canonical_payload(),
        },
        "candidate_config": {
            "fingerprint": config_fingerprint,
            "schema_version": config["schema_version"],
        },
        "validation_scores": scoreboard,
        "artifact": asdict(artifact),
    }
    result_path = output_dir / "locked-result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the preregistered full Criteo v2.1 locked targeting benchmark."
    )
    parser.add_argument("--data-path", type=Path)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=_REPO_ROOT / ".benchmark-data" / "criteo-uplift-v2.1",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_REPO_ROOT / "benchmark-results" / "criteo-v2.1-visit-top10",
    )
    parser.add_argument("--plan", type=Path, default=_DEFAULT_PLAN)
    parser.add_argument("--candidate-config", type=Path, default=_DEFAULT_CANDIDATES)
    parser.add_argument("--chunk-size", type=int, default=250_000)
    parser.add_argument("--prediction-batch-size", type=int, default=250_000)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_full_criteo(
        data_path=args.data_path,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        plan_path=args.plan,
        candidate_config_path=args.candidate_config,
        chunk_size=args.chunk_size,
        prediction_batch_size=args.prediction_batch_size,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
