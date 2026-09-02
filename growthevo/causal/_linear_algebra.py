"""Small dependency-free linear algebra primitives for causal reference models."""

from __future__ import annotations

from math import fsum, sqrt
from typing import Sequence


def solve_linear_system(matrix: list[list[float]], target: list[float]) -> list[float]:
    """Solve a dense square system with pivoted Gauss-Jordan elimination."""

    n = len(target)
    if len(matrix) != n or any(len(row) != n for row in matrix):
        raise ValueError("matrix must be square and match target dimension")

    augmented = [list(row) + [float(rhs)] for row, rhs in zip(matrix, target, strict=True)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("linear system is singular; increase ridge regularization")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]

        scale = augmented[col][col]
        augmented[col] = [value / scale for value in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor == 0.0:
                continue
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[col], strict=True)
            ]
    return [augmented[row][-1] for row in range(n)]


def invert_matrix(matrix: list[list[float]]) -> tuple[tuple[float, ...], ...]:
    """Invert a dense square matrix through repeated linear solves."""

    n = len(matrix)
    columns: list[list[float]] = []
    for column in range(n):
        target = [0.0] * n
        target[column] = 1.0
        columns.append(solve_linear_system(matrix, target))
    return tuple(
        tuple(columns[column][row] for column in range(n))
        for row in range(n)
    )


def mahalanobis_distance(
    features: Sequence[float],
    center: Sequence[float],
    precision: Sequence[Sequence[float]],
) -> float:
    """Compute Mahalanobis distance for an already-regularized precision matrix."""

    delta = [float(value) - float(mean) for value, mean in zip(features, center, strict=True)]
    transformed = [
        fsum(weight * value for weight, value in zip(row, delta, strict=True))
        for row in precision
    ]
    squared = fsum(
        value * transformed_value
        for value, transformed_value in zip(delta, transformed, strict=True)
    )
    return sqrt(max(0.0, squared))
