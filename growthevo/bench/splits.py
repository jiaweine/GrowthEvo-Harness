from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from math import floor
from typing import Callable, Generic, Iterable, TypeVar


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DatasetSplit(Generic[T]):
    """Explicit train/validation/test partitions for benchmark protocols."""

    train: tuple[T, ...]
    validation: tuple[T, ...]
    test: tuple[T, ...]

    def __post_init__(self) -> None:
        if not self.train:
            raise ValueError("train split cannot be empty")
        if not self.test:
            raise ValueError("test split cannot be empty")

    @property
    def total_size(self) -> int:
        return len(self.train) + len(self.validation) + len(self.test)


Identity = Callable[[T], str]
Stratum = Callable[[T], str]


def _stable_order_key(identity: str, seed: int) -> bytes:
    payload = f"{seed}\0{identity}".encode("utf-8")
    return blake2b(payload, digest_size=16).digest()


def _partition_counts(
    size: int,
    fractions: tuple[float, float, float],
    *,
    ensure_stratum_coverage: bool,
) -> tuple[int, int, int]:
    raw = [size * fraction for fraction in fractions]
    counts = [floor(value) for value in raw]
    remaining = size - sum(counts)
    order = sorted(
        range(3),
        key=lambda index: (-(raw[index] - counts[index]), index),
    )
    for index in order[:remaining]:
        counts[index] += 1

    positive = [index for index, fraction in enumerate(fractions) if fraction > 0]
    if ensure_stratum_coverage and size >= len(positive):
        for missing in [index for index in positive if counts[index] == 0]:
            donors = [
                index
                for index in positive
                if counts[index] > 1
            ]
            if not donors:
                break
            donor = max(
                donors,
                key=lambda index: (counts[index] - raw[index], counts[index], -index),
            )
            counts[donor] -= 1
            counts[missing] += 1
    return counts[0], counts[1], counts[2]


def deterministic_stratified_split(
    items: Iterable[T],
    *,
    identity: Identity[T],
    stratum: Stratum[T],
    train_fraction: float,
    validation_fraction: float,
    seed: int,
    ensure_stratum_coverage: bool = True,
) -> DatasetSplit[T]:
    """Split without depending on source-file order.

    The caller defines both identity and stratification semantics. This keeps a
    dataset-specific label, treatment arm, campaign, geography, or other grouping
    decision out of the generic splitting algorithm. Test fraction is the
    remainder after train and validation.
    """

    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be in (0, 1)")
    if not 0 <= validation_fraction < 1:
        raise ValueError("validation_fraction must be in [0, 1)")
    test_fraction = 1.0 - train_fraction - validation_fraction
    if test_fraction <= 0:
        raise ValueError("train_fraction + validation_fraction must be < 1")

    rows = list(items)
    if not rows:
        raise ValueError("at least one item is required")

    identities = [identity(row) for row in rows]
    if any(not value for value in identities):
        raise ValueError("split identities cannot be empty")
    if len(set(identities)) != len(identities):
        raise ValueError("split identities must be unique")

    by_stratum: dict[str, list[tuple[str, T]]] = {}
    for row, row_identity in zip(rows, identities, strict=True):
        key = stratum(row)
        by_stratum.setdefault(key, []).append((row_identity, row))

    train: list[T] = []
    validation: list[T] = []
    test: list[T] = []
    fractions = (train_fraction, validation_fraction, test_fraction)
    for key in sorted(by_stratum):
        members = sorted(
            by_stratum[key],
            key=lambda pair: (_stable_order_key(pair[0], seed), pair[0]),
        )
        train_n, validation_n, _ = _partition_counts(
            len(members),
            fractions,
            ensure_stratum_coverage=ensure_stratum_coverage,
        )
        train.extend(row for _, row in members[:train_n])
        validation.extend(
            row for _, row in members[train_n : train_n + validation_n]
        )
        test.extend(row for _, row in members[train_n + validation_n :])

    return DatasetSplit(
        train=tuple(train),
        validation=tuple(validation),
        test=tuple(test),
    )
