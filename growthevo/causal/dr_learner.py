from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from math import ceil, fsum, sqrt
from typing import Iterable, Mapping, Sequence

from growthevo.models import Channel


FeatureVector = tuple[float, ...]


def _validate_features(features: Sequence[float], expected_dim: int | None = None) -> FeatureVector:
    values = tuple(float(value) for value in features)
    if not values:
        raise ValueError("features cannot be empty")
    if expected_dim is not None and len(values) != expected_dim:
        raise ValueError(f"expected {expected_dim} features, got {len(values)}")
    return values


def _solve_linear_system(matrix: list[list[float]], target: list[float]) -> list[float]:
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


def _invert_matrix(matrix: list[list[float]]) -> tuple[tuple[float, ...], ...]:
    n = len(matrix)
    columns: list[list[float]] = []
    for column in range(n):
        target = [0.0] * n
        target[column] = 1.0
        columns.append(_solve_linear_system(matrix, target))
    return tuple(
        tuple(columns[column][row] for column in range(n))
        for row in range(n)
    )


def _mahalanobis_distance(
    features: Sequence[float],
    center: Sequence[float],
    precision: Sequence[Sequence[float]],
) -> float:
    delta = [float(value) - float(mean) for value, mean in zip(features, center, strict=True)]
    transformed = [
        fsum(weight * value for weight, value in zip(row, delta, strict=True))
        for row in precision
    ]
    squared = fsum(value * transformed_value for value, transformed_value in zip(delta, transformed, strict=True))
    return sqrt(max(0.0, squared))


class RidgeRegressor:
    def __init__(self, ridge: float = 1e-3) -> None:
        if ridge <= 0:
            raise ValueError("ridge must be positive")
        self.ridge = float(ridge)
        self._coef: tuple[float, ...] | None = None
        self._feature_dim: int | None = None

    def fit(self, features: Iterable[Sequence[float]], targets: Iterable[float]) -> "RidgeRegressor":
        rows = [tuple(float(value) for value in row) for row in features]
        ys = [float(value) for value in targets]
        if not rows or len(rows) != len(ys):
            raise ValueError("features and targets must be non-empty and aligned")
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

        self._coef = tuple(_solve_linear_system(gram, rhs))
        self._feature_dim = dim
        return self

    def predict_one(self, features: Sequence[float]) -> float:
        if self._coef is None or self._feature_dim is None:
            raise RuntimeError("regressor must be fitted before prediction")
        row = _validate_features(features, self._feature_dim)
        return self._coef[0] + fsum(
            coefficient * value
            for coefficient, value in zip(self._coef[1:], row, strict=True)
        )

    def predict(self, features: Iterable[Sequence[float]]) -> tuple[float, ...]:
        return tuple(self.predict_one(row) for row in features)


@dataclass(frozen=True, slots=True)
class LoggedTreatmentRecord:
    unit_id: str
    features: FeatureVector
    action: Channel
    outcome: float
    action_propensities: Mapping[Channel, float]

    def __post_init__(self) -> None:
        if not self.unit_id:
            raise ValueError("unit_id cannot be empty")
        _validate_features(self.features)
        if self.action not in self.action_propensities:
            raise ValueError("logged action must have a propensity")
        probabilities = [float(value) for value in self.action_propensities.values()]
        if any(value < 0.0 or value > 1.0 for value in probabilities):
            raise ValueError("action propensities must be in [0, 1]")
        if abs(fsum(probabilities) - 1.0) > 1e-6:
            raise ValueError("action propensities must sum to 1")
        if self.action_propensities[self.action] <= 0.0:
            raise ValueError("logged action propensity must be positive")


@dataclass(frozen=True, slots=True)
class CATEEstimate:
    treatment: Channel
    control: Channel
    effect: float
    uncertainty: float
    support_score: float
    extrapolation_distance: float


@dataclass(frozen=True, slots=True)
class FittedTreatmentEffect:
    treatment: Channel
    control: Channel
    model: RidgeRegressor
    residual_scale: float
    sample_size: int
    overlap_coverage: float
    feature_bounds: tuple[tuple[float, float], ...]
    feature_center: FeatureVector = ()
    feature_precision: tuple[tuple[float, ...], ...] = ()
    support_radius: float = 1.0

    def predict(self, features: Sequence[float]) -> CATEEstimate:
        row = _validate_features(features, len(self.feature_bounds))

        bound_distances: list[float] = []
        for value, (low, high) in zip(row, self.feature_bounds, strict=True):
            width = max(1e-9, high - low)
            if value < low:
                bound_distances.append((low - value) / width)
            elif value > high:
                bound_distances.append((value - high) / width)
            else:
                bound_distances.append(0.0)
        bound_extrapolation = fsum(bound_distances) / len(bound_distances)

        radial_extrapolation = 0.0
        if self.feature_center and self.feature_precision:
            distance = _mahalanobis_distance(
                row,
                self.feature_center,
                self.feature_precision,
            )
            radial_extrapolation = max(
                0.0,
                distance / max(1e-9, self.support_radius) - 1.0,
            )

        extrapolation = max(bound_extrapolation, radial_extrapolation)
        uncertainty = self.residual_scale * (1.0 + extrapolation)
        support_score = self.overlap_coverage / (1.0 + extrapolation)
        return CATEEstimate(
            treatment=self.treatment,
            control=self.control,
            effect=self.model.predict_one(row),
            uncertainty=max(0.0, uncertainty),
            support_score=max(0.0, min(1.0, support_score)),
            extrapolation_distance=extrapolation,
        )


class CrossFittedDRLearner:
    """Cross-fitted one-vs-control doubly-robust treatment-effect learner."""

    def __init__(
        self,
        *,
        n_folds: int = 5,
        ridge: float = 1e-3,
        propensity_floor: float = 0.02,
        support_quantile: float = 0.95,
    ) -> None:
        if n_folds < 2:
            raise ValueError("n_folds must be at least 2")
        if ridge <= 0:
            raise ValueError("ridge must be positive")
        if not 0 < propensity_floor < 0.5:
            raise ValueError("propensity_floor must be in (0, 0.5)")
        if not 0.5 <= support_quantile < 1.0:
            raise ValueError("support_quantile must be in [0.5, 1)")
        self.n_folds = n_folds
        self.ridge = ridge
        self.propensity_floor = propensity_floor
        self.support_quantile = support_quantile

    @staticmethod
    def _stable_key(unit_id: str) -> bytes:
        return blake2b(unit_id.encode("utf-8"), digest_size=16).digest()

    def _fold_assignments(
        self,
        rows: list[LoggedTreatmentRecord],
        treatment: Channel,
        control: Channel,
    ) -> list[int]:
        assignments = [-1] * len(rows)
        for action in (treatment, control):
            indices = [index for index, row in enumerate(rows) if row.action is action]
            indices.sort(key=lambda index: self._stable_key(rows[index].unit_id))
            if len(indices) < self.n_folds:
                raise ValueError(
                    f"need at least {self.n_folds} logged rows for {action.value}; got {len(indices)}"
                )
            for position, index in enumerate(indices):
                assignments[index] = position % self.n_folds
        if any(fold < 0 for fold in assignments):
            raise RuntimeError("failed to assign every treatment/control row to a fold")
        return assignments

    def fit(
        self,
        records: Iterable[LoggedTreatmentRecord],
        *,
        treatment: Channel,
        control: Channel = Channel.NO_TREATMENT,
    ) -> FittedTreatmentEffect:
        if treatment is control:
            raise ValueError("treatment and control must differ")
        rows = [row for row in records if row.action in {treatment, control}]
        if not rows:
            raise ValueError("no treatment/control rows available")
        feature_dim = len(rows[0].features)
        if any(len(row.features) != feature_dim for row in rows):
            raise ValueError("all records must share one feature dimension")

        folds = self._fold_assignments(rows, treatment, control)
        pseudo_outcomes = [0.0] * len(rows)
        supported = 0

        for fold in range(self.n_folds):
            train = [row for index, row in enumerate(rows) if folds[index] != fold]
            held_indices = [index for index in range(len(rows)) if folds[index] == fold]
            treatment_train = [row for row in train if row.action is treatment]
            control_train = [row for row in train if row.action is control]
            if not treatment_train or not control_train:
                raise ValueError("every training split must contain treatment and control rows")

            treatment_model = RidgeRegressor(self.ridge).fit(
                (row.features for row in treatment_train),
                (row.outcome for row in treatment_train),
            )
            control_model = RidgeRegressor(self.ridge).fit(
                (row.features for row in control_train),
                (row.outcome for row in control_train),
            )

            for index in held_indices:
                row = rows[index]
                m1 = treatment_model.predict_one(row.features)
                m0 = control_model.predict_one(row.features)
                p1 = float(row.action_propensities.get(treatment, 0.0))
                p0 = float(row.action_propensities.get(control, 0.0))
                pair_probability = p1 + p0
                if pair_probability <= 0.0:
                    raise ValueError("treatment/control propensity mass must be positive")
                raw_e = p1 / pair_probability
                if self.propensity_floor <= raw_e <= 1.0 - self.propensity_floor:
                    supported += 1
                e = max(self.propensity_floor, min(1.0 - self.propensity_floor, raw_e))

                if row.action is treatment:
                    pseudo_outcomes[index] = m1 - m0 + (row.outcome - m1) / e
                else:
                    pseudo_outcomes[index] = m1 - m0 - (row.outcome - m0) / (1.0 - e)

        effect_oof_predictions = [0.0] * len(rows)
        for fold in range(self.n_folds):
            train_indices = [index for index in range(len(rows)) if folds[index] != fold]
            held_indices = [index for index in range(len(rows)) if folds[index] == fold]
            effect_fold_model = RidgeRegressor(self.ridge).fit(
                (rows[index].features for index in train_indices),
                (pseudo_outcomes[index] for index in train_indices),
            )
            for index in held_indices:
                effect_oof_predictions[index] = effect_fold_model.predict_one(rows[index].features)

        residual_scale = sqrt(
            max(
                0.0,
                fsum(
                    (pseudo - prediction) ** 2
                    for pseudo, prediction in zip(
                        pseudo_outcomes,
                        effect_oof_predictions,
                        strict=True,
                    )
                )
                / len(rows),
            )
        )

        effect_model = RidgeRegressor(self.ridge).fit(
            (row.features for row in rows),
            pseudo_outcomes,
        )

        bounds = tuple(
            (
                min(row.features[index] for row in rows),
                max(row.features[index] for row in rows),
            )
            for index in range(feature_dim)
        )
        center = tuple(
            fsum(row.features[index] for row in rows) / len(rows)
            for index in range(feature_dim)
        )
        covariance = [[0.0 for _ in range(feature_dim)] for _ in range(feature_dim)]
        denominator = max(1, len(rows) - 1)
        for row in rows:
            delta = [row.features[index] - center[index] for index in range(feature_dim)]
            for left in range(feature_dim):
                for right in range(feature_dim):
                    covariance[left][right] += delta[left] * delta[right] / denominator
        regularization = max(self.ridge, 1e-6)
        for index in range(feature_dim):
            covariance[index][index] += regularization
        precision = _invert_matrix(covariance)

        training_distances = sorted(
            _mahalanobis_distance(row.features, center, precision) for row in rows
        )
        radius_index = min(
            len(training_distances) - 1,
            max(0, ceil(len(training_distances) * self.support_quantile) - 1),
        )
        support_radius = max(1e-9, training_distances[radius_index])

        return FittedTreatmentEffect(
            treatment=treatment,
            control=control,
            model=effect_model,
            residual_scale=residual_scale,
            sample_size=len(rows),
            overlap_coverage=supported / len(rows),
            feature_bounds=bounds,
            feature_center=center,
            feature_precision=precision,
            support_radius=support_radius,
        )
