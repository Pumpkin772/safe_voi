"""Evaluation-only truth alignment for frozen offline mode discovery."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg", force=True)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from d5freq.evaluation.diagnostic_metrics import (
    ClusteringEvaluation,
    evaluate_clustering_with_private_labels,
)
from d5freq.identification.offline_pipeline import REQUIRED_LABEL_FREE_ARTIFACTS
from d5freq.utils.hashing import sha256_file


REQUIRED_MODE_DISCOVERY_ARTIFACTS: tuple[str, ...] = (
    REQUIRED_LABEL_FREE_ARTIFACTS + ("confusion_matrix.png",)
)


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return value


def _write_json(payload: object, path: Path) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _read_private_metadata(path: str | Path) -> tuple[Mapping[str, Any], ...]:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("private evaluation metadata must be a non-empty JSON array")
    rows: list[Mapping[str, Any]] = []
    for index, raw in enumerate(payload):
        row = _mapping(raw, f"private metadata row {index}")
        required = {"trajectory_id", "mode_name_eval_only", "split"}
        missing = required.difference(row)
        if missing:
            raise ValueError(f"private metadata row {index} is missing {sorted(missing)}")
        rows.append(row)
    return tuple(rows)


def _save_confusion_matrix_from_metrics(
    metrics_path: Path,
    path: Path,
) -> None:
    """Regenerate the confusion plot only from serialized evaluation metrics."""

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    matrix = np.asarray(payload["aligned_confusion_matrix"], dtype=np.int64)
    reference_classes = tuple(payload["reference_classes"])
    x_labels = [str(value) for value in reference_classes] + ["unmatched"]
    y_labels = [str(value) for value in reference_classes]
    figure, axis = plt.subplots(
        figsize=(max(5.2, 0.85 * len(x_labels)), max(4.4, 0.8 * len(y_labels))),
        constrained_layout=True,
    )
    image = axis.imshow(matrix, cmap="Blues", aspect="auto")
    for row in range(matrix.shape[0]):
        for column in range(matrix.shape[1]):
            axis.text(
                column,
                row,
                str(int(matrix[row, column])),
                ha="center",
                va="center",
            )
    axis.set_xticks(
        np.arange(len(x_labels)), labels=x_labels, rotation=30, ha="right"
    )
    axis.set_yticks(np.arange(len(y_labels)), labels=y_labels)
    axis.set_xlabel("Hungarian-aligned discovered label (evaluation only)")
    axis.set_ylabel("private reference label")
    axis.set_title("Discovery confusion matrix (evaluation only)")
    figure.colorbar(image, ax=axis, label="episode count")
    figure.savefig(path, dpi=180)
    plt.close(figure)


def evaluate_discovery_with_private_metadata(
    *,
    output_directory: str | Path,
    private_metadata_path: str | Path,
) -> ClusteringEvaluation:
    """Score frozen component IDs; never write or replace the model library."""

    output = Path(output_directory).expanduser().resolve()
    library_path = output / "mode_library.json"
    assignments_path = output / "cluster_assignments.csv"
    if not library_path.is_file() or not assignments_path.is_file():
        raise FileNotFoundError("label-free library and assignments must exist first")
    library_digest_before = sha256_file(library_path)
    assignments = pd.read_csv(assignments_path)
    required_assignment_columns = {"trajectory_id", "dataset_split", "component_id"}
    if not required_assignment_columns.issubset(assignments.columns):
        raise ValueError("cluster_assignments.csv is missing required public columns")
    private_rows = _read_private_metadata(private_metadata_path)
    private_by_id: dict[str, Mapping[str, Any]] = {}
    for row in private_rows:
        trajectory_id = str(row["trajectory_id"])
        if trajectory_id in private_by_id:
            raise ValueError("private metadata contains duplicate trajectory IDs")
        private_by_id[trajectory_id] = row

    reference_labels: list[object] = []
    for row in assignments.itertuples(index=False):
        trajectory_id = str(row.trajectory_id)
        if trajectory_id not in private_by_id:
            raise ValueError(f"private metadata is missing trajectory {trajectory_id}")
        private = private_by_id[trajectory_id]
        if str(private["split"]) != str(row.dataset_split):
            raise ValueError(f"split mismatch for trajectory {trajectory_id}")
        reference_labels.append(private["mode_name_eval_only"])

    evaluation = evaluate_clustering_with_private_labels(
        assignments["component_id"].to_numpy(dtype=np.int64),
        reference_labels,
    )
    label_free_summary = json.loads(
        (output / "label_free_summary.json").read_text(encoding="utf-8")
    )
    component_count = len(evaluation.component_ids)
    reference_count = len(evaluation.reference_classes)
    count_match = component_count == reference_count
    metrics_path = output / "private_clustering_metrics.json"
    _write_json(
        {
            "schema_version": 1,
            "evaluation_only": True,
            "adjusted_rand_index": evaluation.adjusted_rand_index,
            "normalized_mutual_information": evaluation.normalized_mutual_information,
            "macro_f1": evaluation.macro_f1,
            "component_to_reference_label": {
                str(key): value
                for key, value in evaluation.component_to_reference_label.items()
            },
            "unmatched_component_ids": list(evaluation.unmatched_component_ids),
            "reference_classes": list(evaluation.reference_classes),
            "component_ids": list(evaluation.component_ids),
            "discovered_component_count": component_count,
            "reference_class_count": reference_count,
            "count_match": count_match,
            "mode_count_matches_private_truth": count_match,
            "hit_configured_k_max": bool(
                label_free_summary["hit_candidate_k_max"]
            ),
            "contingency_matrix": evaluation.contingency_matrix.tolist(),
            "aligned_confusion_matrix": evaluation.aligned_confusion_matrix.tolist(),
            "episode_count": len(reference_labels),
            "model_library_sha256_before_private_evaluation": library_digest_before,
        },
        metrics_path,
    )
    _save_confusion_matrix_from_metrics(metrics_path, output / "confusion_matrix.png")
    library_digest_after = sha256_file(library_path)
    if library_digest_after != library_digest_before:
        raise RuntimeError("private evaluation mutated the frozen model library")
    if not (output / "confusion_matrix.png").is_file():
        raise RuntimeError("private evaluation did not produce confusion_matrix.png")
    return evaluation


__all__ = [
    "REQUIRED_MODE_DISCOVERY_ARTIFACTS",
    "evaluate_discovery_with_private_metadata",
]
