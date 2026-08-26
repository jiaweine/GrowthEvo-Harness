from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from math import fsum, sqrt
from typing import Callable, Iterable, Mapping, Protocol, Sequence

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
    """Solve a small dense linear system with partial-pivot Gauss-Jordan elimination."""

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


class Regressor(Protocol):
    """Minimal regression contract used by the causal cross-fitting pipeline."""

    def fit(self, features: Iterable[Sequence[float]], targets: Iterable[float]) -> "Regressor": ...

    def predict_one(self, features: Sequence[float]) -> float: ...

    def predict(self, features: Iterable[Sequence[float]]) -> tuple[float, ...]: ...


RegressorFactory = Callable[[], Regressor]


class RidgeRegressor:
    """Dependency-free ridge backend for tests and transparent reference runs."""

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
    """One logged decision with the full behavior-policy probability vector.

    ``group_id`` is optional but important for repeated-user or clustered data.
    When supplied, all rows from the same group are kept in one nuisance fold so
    cross-fitting cannot leak a user's outcome history across train and holdout.
    """

    unit_id: str
    features: FeatureVector
    action: Channel
    outcome: float
    action_propensities: Mapping[Channel, float]
    group_id: str | None = None

    def __post_init__(self) -> None:
        if not self.unit_id:
            raise ValueError("unit_id cannot be empty")
        if self.group_id is not None and not self.group_id:
            raise ValueError("group_id cannot be empty when provided")
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
    """Fitted one-vs-control DR learner with explicit support diagnostics.

    ``uncertainty`` uses second-stage out-of-fold residual scale plus feature
    extrapolation. It remains a model diagnostic, not a causal confidence
    interval; deployment evidence still belongs to randomized/logged evaluation.
    """

    treatment: Channel
    control: Channel
    model: Regressor
    residual_scale: float
    sample_size: int
    overlap_coverage: float
    feature_bounds: tuple[tuple[float, float], ...]

    def predict(self, features: Sequence[float]) -> CATEEstimate:
        row = _validate_features(features, len(self.feature_bounds))
        distances: list[float] = []
        for value, (low, high) in zip(row, self.feature_bounds, strict=True):
            width = max(1e-9, high - low)
            if value < low:
                distances.append((low - value) / width)
            elif value > high:
                distances.append((value - high) / width)
            else:
                distances.append(0.0)
        extrapolation = fsum(distances) / len(distances)
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
    """Cross-fitted one-vs-control doubly robust treatment-effect learner.

    Outcome and effect regressors are factories rather than fixed model classes.
    This keeps the orthogonalization/cross-fitting contract stable while allowing
    production experiments to plug in forests, boosting, neural estimators, or
    other regressors without editing causal logic.
    """

    def __init__(
        self,
        *,
        n_folds: int = 5,
        ridge: float = 1e-3,
        propensity_floor: float = 0.02,
        outcome_model_factory: RegressorFactory | None = None,
        effect_model_factory: RegressorFactory | None = None,
    ) -> None:
        if n_folds < 2:
            raise ValueError("n_folds must be at least 2")
        if ridge <= 0:
            raise ValueError("ridge must be positive")
        if not 0 < propensity_floor < 0.5:
            raise ValueError("propensity_floor must be in (0, 0.5)")
        self.n_folds = n_folds
        self.ridge = ridge
        self.propensity_floor = propensity_floor
        self.outcome_model_factory = outcome_model_factory or (lambda: RidgeRegressor(self.ridge))
        self.effect_model_factory = effect_model_factory or (lambda: RidgeRegressor(self.ridge))

    @staticmethod
    def _stable_key(value: str) -> bytes:
        return blake2b(value.encode("utf-8"), digest_size=16).digest()

    def _fold_assignments(
        self,
        rows: list[LoggedTreatmentRecord],
        treatment: Channel,
        control: Channel,
    ) -> list[int]:
        if any(row.group_id is not None for row in rows):
            assignments = [
                int.from_bytes(self._stable_key(row.group_id or row.unit_id), "big") % self.n_folds
                for row in rows
            ]
            for fold in range(self.n_folds):
                train_actions = {
                    row.action for index, row in enumerate(rows) if assignments[index] != fold
                }
                if treatment not in train_actions or control not in train_actions:
                    raise ValueError(
                        "group-aware folds leave a training split without treatment/control rows; "
                        "reduce n_folds or provide more groups"
                    )
            return assignments

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
        if any(fold < 0 for fold in assignments):  # pragma: no cover - defensive.
            raise RuntimeError("failed to assign every treatment/control row to a fold")
        return assignments

    def _new_outcome_model(self) -> Regressor:
        return self.outcome_model_factory()

    def _new_effect_model(self) -> Regressor:
        return self.effect_model_factory()

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

            treatment_model = self._new_outcome_model().fit(
                (row.features for row in treatment_train),
                (row.outcome for row in treatment_train),
            )
            control_model = self._new_outcome_model().fit(
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
                    pseudo = m1 - m0 + (row.outcome - m1) / e
                else:
                    pseudo = m1 - m0 - (row.outcome - m0) / (1.0 - e)
                pseudo_outcomes[index] = pseudo

        effect_oof_predictions = [0.0] * len(rows)
        for fold in range(self.n_folds):
            train_indices = [index for index in range(len(rows)) if folds[index] != fold]
            held_indices = [index for index in range(len(rows)) if folds[index] == fold]
            if not held_indices:
                continue
            effect_fold_model = self._new_effect_model().fit(
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
        effect_model = self._new_effect_model().fit(
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
        return FittedTreatmentEffect(
            treatment=treatment,
            control=control,
            model=effect_model,
            residual_scale=residual_scale,
            sample_size=len(rows),
            overlap_coverage=supported / len(rows),
            feature_bounds=bounds,
        )
