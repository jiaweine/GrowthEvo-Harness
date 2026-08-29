from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping


PathLike = str | Path
OpenBanditActionContext = Mapping[int, Mapping[str, str]]


def load_open_bandit_item_context(
    path: PathLike,
    *,
    allowed_item_ids: Iterable[int] | None = None,
) -> dict[int, dict[str, str]]:
    """Load Open Bandit's item/action context without inventing feature types.

    The official pipeline separates user context from ``item_context.csv`` and
    applies its own encoding downstream. This loader therefore preserves every
    ``item_feature_*`` value as the raw anonymized string. A model backend can
    choose categorical encoding, embeddings, target encoding, or documented
    numeric treatment explicitly rather than inheriting an accidental ordinal
    interpretation from the data adapter.
    """

    selected = None if allowed_item_ids is None else {int(item_id) for item_id in allowed_item_ids}
    result: dict[int, dict[str, str]] = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        if "item_id" not in fieldnames:
            raise ValueError("missing Open Bandit item-context column: item_id")
        feature_names = tuple(name for name in fieldnames if name.startswith("item_feature"))
        if not feature_names:
            raise ValueError("Open Bandit item context has no item_feature columns")

        for row in reader:
            try:
                item_id = int(float(row["item_id"]))
            except (TypeError, ValueError) as exc:
                raise ValueError("Open Bandit item_id must be numeric") from exc
            if selected is not None and item_id not in selected:
                continue
            if item_id in result:
                raise ValueError(f"duplicate Open Bandit item_id: {item_id}")
            result[item_id] = {name: row[name] for name in feature_names}

    if not result:
        raise ValueError("Open Bandit item context produced no selected rows")
    return result
