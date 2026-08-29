from __future__ import annotations

from gzip import open as gzip_open
from pathlib import Path
import csv
from typing import Any, Iterable, TextIO


PathLike = str | Path


def _open_csv(path: PathLike) -> TextIO:
    resolved = Path(path)
    if resolved.suffix == ".gz":
        return gzip_open(resolved, mode="rt", encoding="utf-8", newline="")
    return resolved.open(mode="r", encoding="utf-8", newline="")


def _coerce_feature(value: str) -> Any:
    if value == "":
        return ""
    try:
        integer = int(value)
    except ValueError:
        pass
    else:
        if str(integer) == value or value in {f"+{integer}", f"-{abs(integer)}"}:
            return integer
    try:
        return float(value)
    except ValueError:
        return value


def _load_feature_table(
    path: PathLike,
    *,
    id_column: str,
    selected_ids: Iterable[int] | None,
    max_rows: int | None,
) -> dict[int, dict[str, Any]]:
    if max_rows is not None and max_rows <= 0:
        raise ValueError("max_rows must be positive when provided")
    selected = set(selected_ids) if selected_ids is not None else None
    features: dict[int, dict[str, Any]] = {}
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        if id_column not in fieldnames:
            raise ValueError(f"missing required column: {id_column}")
        for row_index, row in enumerate(reader):
            if max_rows is not None and row_index >= max_rows:
                break
            try:
                entity_id = int(row[id_column])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"column {id_column!r} must contain integer ids") from exc
            if selected is not None and entity_id not in selected:
                continue
            features[entity_id] = {
                name: _coerce_feature(row[name])
                for name in fieldnames
                if name != id_column
            }
    if selected is None and not features:
        raise ValueError("feature file produced no rows")
    return features


def load_kuairand_user_features(
    path: PathLike,
    *,
    user_ids: Iterable[int] | None = None,
    max_rows: int | None = None,
) -> dict[int, dict[str, Any]]:
    """Load official KuaiRand user features, optionally filtering by user id.

    The official table mixes numeric and categorical attributes. Values retain
    that distinction instead of forcing categorical activity/range fields into
    arbitrary ordinal numbers.
    """

    return _load_feature_table(
        path,
        id_column="user_id",
        selected_ids=user_ids,
        max_rows=max_rows,
    )


def load_kuairand_video_features(
    path: PathLike,
    *,
    video_ids: Iterable[int] | None = None,
    max_rows: int | None = None,
) -> dict[int, dict[str, Any]]:
    """Load official KuaiRand video features, optionally filtering by video id.

    Filtering is important for large catalogs: callers can collect the video ids
    present in the experiment split and avoid materializing unrelated items.
    """

    return _load_feature_table(
        path,
        id_column="video_id",
        selected_ids=video_ids,
        max_rows=max_rows,
    )
