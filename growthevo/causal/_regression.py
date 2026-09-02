"""Minimal regression contracts and the dependency-free ridge reference backend."""

from __future__ import annotations

from math import fsum, isfinite
from typing import Callable, Iterable, Protocol, Sequence

from ._linear_algebra import solve_linear_system


FeatureVector = tuple[float, ...]


def validate_features(
    features: Sequence[float],
    expected_dim: int | None = None,
) -> FeatureVector:
    values = tuple(float(value) for value in features)
    if not values:
        raise ValueError("features cannot be empty")
    if any(not isfinite(value) for value in values):
        raise ValueError("features must be finite")
    if expected_dim is not None and len(values) != expected_dim:
        raise ValueError(f"expected {expected_dim} features, got {len(values)}")
    return values


class Regressor(Protocol):
    """Minimal backend contract for nuisance and second-stage CATE models."""

    def fit(
        self,
        features: Iterable[Sequence[float]],
        targets: Iterable[float],
    ) -> "Regressor": ...

    def predict_one(self, features: Sequence[float]) -> float: ...


RegressorFactory = Callable[[], Regressor]


class RidgeRegressor:
    """Dependency-free auditable reference backend, not a performance ceiling."""

    def __init__(self, ridge: float = 1e-3) -> None:
        if ridge <= 0:
            raise ValueError("ridge must be positive")
        self.ridge = float(ridge)
        self._coef: tuple[float, ...] | None = None
        self._feature_dim: int | None = None

    def fit(
        self,
        features: Iterable[Sequence[float]],
        targets: Iterable[float],
    ) -> "RidgeRegressor":
        rows = [tuple(float(value) for value in row) for row in features]
        ys = [float(value) for value in targets]
        if not rows or len(rows) != len(ys):
            raise ValueError("features and targets must be non-empty and aligned")
        if any(not isfinite(target) for target in ys):
            raise ValueError("targets must be finite")
        dim = len(rows[0])
        if dim == 0 or any(len(row) != dim for row in rows):
            raise ValueError("all feature rows must have one consistent non-zero dimension")

        design = [(1.0, *row) for row in rows]
        width = dim + 1
        gram = [[0.0 for _ in range(width)] for _ in range(width)]
        rhs = [0.0 for _ in range(width)]
        for row, target in zip(design, ys, strict=True):
            for left in range(width):
                rhs[left] += row[left] * target
                for right in range(width):
                    gram[left][right] += row[left] * row[right]
        for index in range(1, width):
            gram[index][index] += self.ridge

        self._coef = tuple(solve_linear_system(gram, rhs))
        self._feature_dim = dim
        return self

    def predict_one(self, features: Sequence[float]) -> float:
        if self._coef is None or self._feature_dim is None:
            raise RuntimeError("regressor must be fitted before prediction")
        row = validate_features(features, self._feature_dim)
        return self._coef[0] + fsum(
            coefficient * value
            for coefficient, value in zip(self._coef[1:], row, strict=True)
        )

    def predict(self, features: Iterable[Sequence[float]]) -> tuple[float, ...]:
        return tuple(self.predict_one(row) for row in features)
