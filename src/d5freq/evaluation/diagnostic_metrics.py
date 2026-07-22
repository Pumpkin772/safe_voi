"""Evaluation-only clustering and mode distinguishability diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import Hashable, Mapping, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score, f1_score, normalized_mutual_info_score


FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
ARX_PARAMETER_COUNT = 7


def _finite_vector(value: ArrayLike, size: int, name: str) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError(f"{name} must be real-valued")
    vector = np.asarray(raw, dtype=np.float64)
    if vector.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},)")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must contain only finite values")
    return vector.copy()


def _regression_matrix(value: ArrayLike) -> FloatArray:
    raw = np.asarray(value)
    if np.iscomplexobj(raw):
        raise TypeError("regression_vectors must be real-valued")
    matrix = np.asarray(raw, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] != ARX_PARAMETER_COUNT:
        raise ValueError(
            f"regression_vectors must have shape (n, {ARX_PARAMETER_COUNT}) with n > 0"
        )
    if not np.all(np.isfinite(matrix)):
        raise ValueError("regression_vectors must contain only finite values")
    return matrix.copy()


def _nonnegative_real(value: float, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    if normalized < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return normalized


def one_step_prediction_difference(
    theta_m: ArrayLike,
    theta_n: ArrayLike,
    regression_vectors: ArrayLike,
) -> FloatArray:
    """Compute every equation-(38) prediction difference."""

    first = _finite_vector(theta_m, ARX_PARAMETER_COUNT, "theta_m")
    second = _finite_vector(theta_n, ARX_PARAMETER_COUNT, "theta_n")
    phi = _regression_matrix(regression_vectors)
    return np.asarray(phi @ (first - second), dtype=np.float64)


def distinguishability_information(
    theta_m: ArrayLike,
    theta_n: ArrayLike,
    regression_vectors: ArrayLike,
    *,
    residual_variance_m: float,
    residual_variance_n: float,
) -> float:
    """Return cumulative pairwise information from equations (38)--(39)."""

    variance_m = _nonnegative_real(residual_variance_m, "residual_variance_m")
    variance_n = _nonnegative_real(residual_variance_n, "residual_variance_n")
    denominator = variance_m + variance_n
    if denominator <= 0.0:
        raise ValueError("the sum of residual variances must be strictly positive")
    differences = one_step_prediction_difference(theta_m, theta_n, regression_vectors)
    return float(np.dot(differences, differences) / denominator)


def pairwise_distinguishability_matrix(
    theta_by_component: ArrayLike,
    residual_variances: ArrayLike,
    regression_vectors: ArrayLike,
) -> FloatArray:
    """Evaluate equation (39) for every pair using one common excitation set."""

    raw_theta = np.asarray(theta_by_component)
    if np.iscomplexobj(raw_theta):
        raise TypeError("theta_by_component must be real-valued")
    theta = np.asarray(raw_theta, dtype=np.float64)
    if theta.ndim != 2 or theta.shape[0] == 0 or theta.shape[1] != ARX_PARAMETER_COUNT:
        raise ValueError(
            f"theta_by_component must have shape (k, {ARX_PARAMETER_COUNT}) with k > 0"
        )
    if not np.all(np.isfinite(theta)):
        raise ValueError("theta_by_component must contain only finite values")
    raw_variances = np.asarray(residual_variances)
    if np.iscomplexobj(raw_variances):
        raise TypeError("residual_variances must be real-valued")
    variances = np.asarray(raw_variances, dtype=np.float64)
    if variances.shape != (theta.shape[0],):
        raise ValueError("residual_variances must have one entry per component")
    if not np.all(np.isfinite(variances)) or np.any(variances < 0.0):
        raise ValueError("residual_variances must be finite and non-negative")
    phi = _regression_matrix(regression_vectors)
    component_count = theta.shape[0]
    information = np.zeros((component_count, component_count), dtype=np.float64)
    for first in range(component_count):
        for second in range(first + 1, component_count):
            value = distinguishability_information(
                theta[first],
                theta[second],
                phi,
                residual_variance_m=float(variances[first]),
                residual_variance_n=float(variances[second]),
            )
            information[first, second] = value
            information[second, first] = value
    return information


def _component_ids(values: ArrayLike) -> IntArray:
    raw = np.asarray(values)
    if raw.ndim != 1 or raw.size == 0:
        raise ValueError("discovered_component_ids must be a non-empty vector")
    if not np.issubdtype(raw.dtype, np.integer):
        raise TypeError("discovered_component_ids must contain integers")
    normalized = np.asarray(raw, dtype=np.int64)
    if np.any(normalized < 0):
        raise ValueError("discovered_component_ids must be non-negative")
    return normalized


def _reference_values(values: Sequence[Hashable] | ArrayLike) -> tuple[Hashable, ...]:
    array = np.asarray(values, dtype=object)
    if array.ndim != 1 or array.size == 0:
        raise ValueError("reference_labels must be a non-empty vector")
    normalized: list[Hashable] = []
    for value in array.tolist():
        if value is None:
            raise ValueError("reference_labels cannot contain None")
        try:
            hash(value)
        except TypeError as exc:
            raise TypeError("reference_labels must be hashable") from exc
        if isinstance(value, Real) and not isinstance(value, (bool, np.bool_)):
            if not math.isfinite(float(value)):
                raise ValueError("reference_labels cannot contain non-finite values")
        normalized.append(value)
    return tuple(normalized)


def _ordered_unique(values: Sequence[Hashable]) -> tuple[Hashable, ...]:
    unique = set(values)
    return tuple(sorted(unique, key=lambda value: (type(value).__qualname__, repr(value))))


@dataclass(frozen=True, slots=True)
class ClusteringEvaluation:
    """Private-label evaluation output; never consumed by a controller."""

    adjusted_rand_index: float
    normalized_mutual_information: float
    macro_f1: float
    component_ids: tuple[int, ...]
    reference_classes: tuple[Hashable, ...]
    component_to_reference_label: Mapping[int, Hashable]
    unmatched_component_ids: tuple[int, ...]
    contingency_matrix: IntArray
    aligned_confusion_matrix: IntArray

    def __post_init__(self) -> None:
        for name in (
            "adjusted_rand_index",
            "normalized_mutual_information",
            "macro_f1",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            object.__setattr__(self, name, value)
        contingency = np.asarray(self.contingency_matrix, dtype=np.int64)
        aligned = np.asarray(self.aligned_confusion_matrix, dtype=np.int64)
        if contingency.shape != (len(self.component_ids), len(self.reference_classes)):
            raise ValueError("contingency_matrix shape is inconsistent with labels")
        if aligned.shape != (len(self.reference_classes), len(self.reference_classes) + 1):
            raise ValueError("aligned_confusion_matrix has an invalid shape")
        if np.any(contingency < 0) or np.any(aligned < 0):
            raise ValueError("count matrices must be non-negative")
        contingency = contingency.copy()
        aligned = aligned.copy()
        contingency.setflags(write=False)
        aligned.setflags(write=False)
        object.__setattr__(self, "component_to_reference_label", dict(self.component_to_reference_label))
        object.__setattr__(self, "contingency_matrix", contingency)
        object.__setattr__(self, "aligned_confusion_matrix", aligned)


def evaluate_clustering_with_private_labels(
    discovered_component_ids: ArrayLike,
    reference_labels: Sequence[Hashable] | ArrayLike,
) -> ClusteringEvaluation:
    """Align discovered IDs for ARI/NMI/macro-F1 reporting only.

    Rectangular assignments are supported.  Components without a one-to-one
    match are sent to a dedicated unmatched confusion-matrix column and are
    consequently counted as false negatives in macro-F1.
    """

    components = _component_ids(discovered_component_ids)
    references = _reference_values(reference_labels)
    if components.size != len(references):
        raise ValueError("discovered IDs and reference labels must have equal lengths")
    component_classes = tuple(int(value) for value in np.unique(components).tolist())
    reference_classes = _ordered_unique(references)
    component_index = {value: index for index, value in enumerate(component_classes)}
    reference_index = {value: index for index, value in enumerate(reference_classes)}
    reference_encoded = np.asarray(
        [reference_index[value] for value in references], dtype=np.int64
    )
    contingency = np.zeros(
        (len(component_classes), len(reference_classes)), dtype=np.int64
    )
    for component, reference in zip(components.tolist(), references, strict=True):
        contingency[component_index[component], reference_index[reference]] += 1

    matched_rows, matched_columns = linear_sum_assignment(-contingency)
    row_to_column = {
        int(row): int(column)
        for row, column in zip(matched_rows.tolist(), matched_columns.tolist(), strict=True)
    }
    mapping = {
        component_classes[row]: reference_classes[column]
        for row, column in row_to_column.items()
    }
    unmatched_components = tuple(
        component_classes[row]
        for row in range(len(component_classes))
        if row not in row_to_column
    )

    unmatched_column = len(reference_classes)
    aligned_prediction = np.asarray(
        [
            row_to_column.get(component_index[int(component)], unmatched_column)
            for component in components
        ],
        dtype=np.int64,
    )
    aligned_confusion = np.zeros(
        (len(reference_classes), len(reference_classes) + 1), dtype=np.int64
    )
    for reference, prediction in zip(
        reference_encoded.tolist(), aligned_prediction.tolist(), strict=True
    ):
        aligned_confusion[reference, prediction] += 1

    macro_f1 = float(
        f1_score(
            reference_encoded,
            aligned_prediction,
            labels=np.arange(len(reference_classes), dtype=np.int64),
            average="macro",
            zero_division=0.0,
        )
    )
    return ClusteringEvaluation(
        adjusted_rand_index=float(adjusted_rand_score(reference_encoded, components)),
        normalized_mutual_information=float(
            normalized_mutual_info_score(reference_encoded, components)
        ),
        macro_f1=macro_f1,
        component_ids=component_classes,
        reference_classes=reference_classes,
        component_to_reference_label=mapping,
        unmatched_component_ids=unmatched_components,
        contingency_matrix=contingency,
        aligned_confusion_matrix=aligned_confusion,
    )


__all__ = [
    "ClusteringEvaluation",
    "distinguishability_information",
    "evaluate_clustering_with_private_labels",
    "one_step_prediction_difference",
    "pairwise_distinguishability_matrix",
]
