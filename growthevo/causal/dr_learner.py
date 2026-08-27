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
    """One logged decision with the full behavior-policy probability vector."""

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
    """Fitted one-vs-control DR learner with explicit overlap diagnostics.

    ``overlap_coverage`` records strict positivity (both pairwise propensities
    positive). ``practical_overlap_coverage`` is populated only when a caller
    explicitly selects a practical overlap threshold. ``propensity_clip_fraction``
    is non-zero only when clipping was explicitly requested.

    ``uncertainty`` remains a second-stage OOF residual/extrapolation diagnostic,
    not a calibrated causal confidence interval.
    """

    treatment: Channel
    control: Channel
    model: Regressor
    residual_scale: float
    sample_size: int
    overlap_coverage: float
    feature_bounds: tuple[tuple[float, float], ...]
    practical_overlap_coverage: float | None = None
    propensity_clip_fraction: float = 0.0

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
        base_support = (
            self.practical_overlap_coverage
            if self.practical_overlap_coverage is not None
            else self.overlap_coverage
        )
        support_score = base_support / (1.0 + extrapolation)
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

    No propensity clipping is applied by default. Exact positivity violations are
    rejected because the pairwise treatment effect is not identified there.
    Optional practical-overlap diagnostics and optional propensity clipping are
    separate explicit choices so a numerical stabilizer cannot masquerade as a
    support definition.
    """

    def __init__(
        self,
        *,
        n_folds: int = 5,
        ridge: float = 1e-3,
        practical_overlap_floor: float | None = None,
        propensity_clip_floor: float | None = None,
        outcome_model_factory: RegressorFactory | None = None,
        effect_model_factory: RegressorFactory | None = None,
    ) -> None:
        if n_folds < 2:
            raise ValueError("n_folds must be at least 2")
        if ridge <= 0:
            raise ValueError("ridge must be positive")
        for name, value in (
            ("practical_overlap_floor", practical_overlap_floor),
            ("propensity_clip_floor", propensity_clip_floor),
        ):
            if value is not None and not 0 < value < 0.5:
                raise ValueError(f"{name} must be in (0, 0.5) when provided")
        self.n_folds = n_folds
        self.ridge = ridge
        self.practical_overlap_floor = practical_overlap_floor
        self.propensity_clip_floor = propensity_clip_floor
        self.outcome_model_factory = outcome_model_factory or (lambda: RidgeRegressor(self.ridge))
        self.effect_model_factory = effect_model_factory or (lambda: RidgeRegressor(self.ridge))

    @staticmethod
    def _stable_key(value: str) -> bytes:
        return blake2b(value.encode("utf-8"), digest_size=16).digest()

    def _group_fold_assignments(
        self,
        rows: list[LoggedTreatmentRecord],
        treatment: Channel,
        control: Channel,
    ) -> list[int]:
        groups: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            key = row.group_id or row.unit_id
            groups.setdefault(key, []).append(index)
        if len(groups) < self.n_folds:
            raise ValueError(
                f"need at least {self.n_folds} distinct groups for group-aware cross-fitting; "
                f"got {len(groups)}"
            )

        actions = (treatment, control)
        action_totals = {action: sum(row.action is action for row in rows) for action in actions}
        if any(total == 0 for total in action_totals.values()):
            raise ValueError("group-aware cross-fitting requires treatment and control rows")

        group_counts: dict[str, dict[Channel, int]] = {}
        for key, indices in groups.items():
            group_counts[key] = {
                action: sum(rows[index].action is action for index in indices)
                for action in actions
            }

        ordered_groups = sorted(
            groups,
            key=lambda key: (
                -len(groups[key]),
                -max(group_counts[key].values()),
                self._stable_key(key),
            ),
        )
        fold_counts = [dict.fromkeys(actions, 0) for _ in range(self.n_folds)]
        fold_sizes = [0 for _ in range(self.n_folds)]
        group_to_fold: dict[str, int] = {}
        target_share = 1.0 / self.n_folds

        def global_imbalance(candidate_fold: int, counts: Mapping[Channel, int], size: int) -> tuple[float, float]:
            class_deviation = 0.0
            size_deviation = 0.0
            for fold in range(self.n_folds):
                fold_size = fold_sizes[fold] + (size if fold == candidate_fold else 0)
                size_deviation += (fold_size / len(rows) - target_share) ** 2
                for action in actions:
                    count = fold_counts[fold][action] + (
                        counts[action] if fold == candidate_fold else 0
                    )
                    class_deviation += (
                        count / action_totals[action] - target_share
                    ) ** 2
            return class_deviation, size_deviation

        for position, key in enumerate(ordered_groups):
            counts = group_counts[key]
            size = len(groups[key])
            empty_folds = [fold for fold, fold_size in enumerate(fold_sizes) if fold_size == 0]
            remaining_groups = len(ordered_groups) - position
            if empty_folds and remaining_groups <= len(empty_folds):
                eligible_folds = empty_folds
            elif position < self.n_folds:
                eligible_folds = empty_folds
            else:
                eligible_folds = list(range(self.n_folds))

            candidates: list[tuple[float, float, int, int]] = []
            for fold in eligible_folds:
                class_deviation, size_deviation = global_imbalance(fold, counts, size)
                candidates.append((class_deviation, size_deviation, fold_sizes[fold], fold))
            _, _, _, selected_fold = min(candidates)
            group_to_fold[key] = selected_fold
            fold_sizes[selected_fold] += size
            for action in actions:
                fold_counts[selected_fold][action] += counts[action]

        assignments = [group_to_fold[row.group_id or row.unit_id] for row in rows]
        for fold in range(self.n_folds):
            held_indices = [index for index, assigned in enumerate(assignments) if assigned == fold]
            if not held_indices:
                raise RuntimeError("group-aware fold assignment produced an empty holdout fold")
            train_actions = {
                row.action for index, row in enumerate(rows) if assignments[index] != fold
            }
            if treatment not in train_actions or control not in train_actions:
                raise ValueError(
                    "group-aware folds leave a training split without treatment/control rows; "
                    "reduce n_folds or provide more groups"
                )
        return assignments

    def _fold_assignments(
        self,
        rows: list[LoggedTreatmentRecord],
        treatment: Channel,
        control: Channel,
    ) -> list[int]:
        if any(row.group_id is not None for row in rows):
            return self._group_fold_assignments(rows, treatment, control)

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
        strict_supported = 0
        practical_supported = 0
        clipped = 0

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
                if not 0.0 < raw_e < 1.0:
                    raise ValueError(
                        "pairwise positivity violated: treatment and control must both have "
                        "positive logging probability for every fitted record"
                    )
                strict_supported += 1

                if self.practical_overlap_floor is not None and (
                    self.practical_overlap_floor
                    <= raw_e
                    <= 1.0 - self.practical_overlap_floor
                ):
                    practical_supported += 1

                e = raw_e
                if self.propensity_clip_floor is not None:
                    clipped_e = max(
                        self.propensity_clip_floor,
                        min(1.0 - self.propensity_clip_floor, raw_e),
                    )
                    if abs(clipped_e - raw_e) > 1e-15:
                        clipped += 1
                    e = clipped_e

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
        practical_coverage = (
            practical_supported / len(rows)
            if self.practical_overlap_floor is not None
            else None
        )
        return FittedTreatmentEffect(
            treatment=treatment,
            control=control,
            model=effect_model,
            residual_scale=residual_scale,
            sample_size=len(rows),
            overlap_coverage=strict_supported / len(rows),
            practical_overlap_coverage=practical_coverage,
            propensity_clip_fraction=clipped / len(rows),
            feature_bounds=bounds,
        )
