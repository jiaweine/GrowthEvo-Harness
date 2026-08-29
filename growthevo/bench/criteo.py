from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from gzip import open as gzip_open
from hashlib import blake2b
from math import fsum
from pathlib import Path
from typing import Literal, Mapping, TextIO

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


def _row_fingerprint(row: Mapping[str, str], fieldnames: tuple[str, ...]) -> str:
    """Stable identity for a physical benchmark row independent of file position."""

    payload = "\x1f".join(f"{name}\x1e{row.get(name, '')}" for name in fieldnames)
    return blake2b(payload.encode("utf-8"), digest_size=16).hexdigest()


@dataclass(frozen=True, slots=True)
class CriteoUpliftData:
    """Randomized advertising records with explicit propensity provenance.

    ``treatment_propensity`` is the propensity actually written into each causal
    record. ``observed_treatment_share`` is always reported separately. When a
    design propensity is supplied by the experiment protocol,
    ``propensity_source`` is ``design``; otherwise the loader uses the loaded
    cohort's empirical arm share and marks that fallback explicitly.
    """

    records: tuple[LoggedTreatmentRecord, ...]
    treatment_propensity: float
    observed_treatment_share: float
    propensity_source: Literal["design", "empirical"]
    outcome_name: Literal["visit", "conversion"]


def load_criteo_uplift(
    path: PathLike,
    *,
    outcome: Literal["visit", "conversion"] = "visit",
    max_rows: int | None = None,
    treatment_propensity: float | None = None,
) -> CriteoUpliftData:
    """Load the randomized Criteo uplift benchmark without guessing design facts.

    Randomized ``treatment`` defines treatment assignment. Post-assignment
    ``exposure`` is never used as treatment. For final causal evaluation, callers
    should pass the documented design assignment probability when known. The
    empirical loaded-arm share remains available as a transparent fallback for
    development/smoke tests and is labelled as such.

    Row identities are derived from row content rather than source-file position,
    so deterministic benchmark splits do not change merely because the same
    cohort is reordered. Exact duplicate rows receive deterministic occurrence
    suffixes; because those rows are observationally identical, permuting them
    does not change the resulting multiset of records.

    ``max_rows`` remains a prefix-oriented smoke-test convenience. A final
    benchmark should load the intended cohort explicitly instead of interpreting
    a file prefix as a statistically meaningful sample.
    """

    if max_rows is not None and max_rows <= 0:
        raise ValueError("max_rows must be positive when provided")
    if treatment_propensity is not None and not 0 < treatment_propensity < 1:
        raise ValueError("treatment_propensity must be in (0, 1)")

    feature_names = tuple(f"f{index}" for index in range(12))
    raw: list[tuple[str, tuple[float, ...], bool, float]] = []
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        required = set(feature_names) | {"treatment", outcome}
        missing = required.difference(fieldnames)
        if missing:
            raise ValueError(f"missing Criteo columns: {sorted(missing)}")
        for index, row in enumerate(reader):
            if max_rows is not None and index >= max_rows:
                break
            features = tuple(_read_float(row, name) for name in feature_names)
            treatment_value = _read_float(row, "treatment")
            if treatment_value not in {0.0, 1.0}:
                raise ValueError("Criteo treatment must be binary")
            outcome_value = _read_float(row, outcome)
            if outcome_value not in {0.0, 1.0}:
                raise ValueError(f"Criteo {outcome} must be binary")
            raw.append(
                (
                    _row_fingerprint(row, fieldnames),
                    features,
                    bool(treatment_value),
                    outcome_value,
                )
            )

    if not raw:
        raise ValueError("Criteo file produced no rows")
    observed_share = fsum(1.0 for _, _, treated, _ in raw if treated) / len(raw)
    if not 0 < observed_share < 1:
        raise ValueError("loaded cohort must contain both treatment and control")

    if treatment_propensity is None:
        propensity = observed_share
        source: Literal["design", "empirical"] = "empirical"
    else:
        propensity = treatment_propensity
        source = "design"

    action_propensities = {
        Channel.NO_TREATMENT: 1.0 - propensity,
        Channel.ADS: propensity,
    }
    occurrences: Counter[str] = Counter()
    records: list[LoggedTreatmentRecord] = []
    for fingerprint, features, treated, y in raw:
        duplicate_index = occurrences[fingerprint]
        occurrences[fingerprint] += 1
        records.append(
            LoggedTreatmentRecord(
                unit_id=f"criteo-{fingerprint}-{duplicate_index}",
                features=features,
                action=Channel.ADS if treated else Channel.NO_TREATMENT,
                outcome=y,
                action_propensities=action_propensities,
            )
        )

    return CriteoUpliftData(
        records=tuple(records),
        treatment_propensity=propensity,
        observed_treatment_share=observed_share,
        propensity_source=source,
        outcome_name=outcome,
    )
