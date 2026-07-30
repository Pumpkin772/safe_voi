"""Run the preregistered control-relevant and passive-identifiability audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from d5freq.evaluation.phase_b2_identifiability import (
    ControlDistanceWeights,
    control_relevant_distance_rows,
    critical_window,
    passive_detection_rows,
    rollout_expected_block,
    visible_output,
)
from d5freq.evaluation.phase_b2_plant import load_plant_b_parameters
from d5freq.models.two_area_plant_b import TwoAreaPlantB


REGIMES = (
    "nominal_available",
    "headroom_or_current_limited",
    "energy_limited",
    "communication_degraded",
    "service_disabled",
    "recovery",
    "structural_ood",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    return parser.parse_args()


def _four_second_signature(
    params: object,
    *,
    regime: str,
    load: tuple[float, float],
) -> np.ndarray:
    model = TwoAreaPlantB(params)
    state = model.initial_state(
        soc=(0.14, 0.14) if regime == "energy_limited" else (0.50, 0.50)
    )
    action = np.asarray(
        (
            min(max(load[0], 0.0), params.sg_capability.reserve_up_pu[0]),
            min(max(load[1], 0.0), params.sg_capability.reserve_up_pu[1]),
            0.0,
            0.0,
        )
    )
    pieces = []
    for _ in range(2):
        block = rollout_expected_block(
            params,
            state=state,
            action=action,
            load_pu=load,
            regime_pair=(regime, regime),
        )
        pieces.append(visible_output(block[:, 1:]))
        state = block[:, -1]
    return np.concatenate(pieces, axis=1)


def _source_confusion_rows(params: object) -> list[dict[str, object]]:
    nominal_zero = _four_second_signature(
        params, regime="nominal_available", load=(0.0, 0.0)
    )
    load_template = (
        _four_second_signature(
            params, regime="nominal_available", load=(0.06, 0.0)
        )
        - nominal_zero
    )
    rows: list[dict[str, object]] = []
    for regime in REGIMES[1:]:
        mode_template = (
            _four_second_signature(params, regime=regime, load=(0.0, 0.0))
            - nominal_zero
        )
        both_template = mode_template + load_template
        signatures = {
            "load_only": load_template,
            "mode_only": mode_template,
            "coincident": _four_second_signature(
                params, regime=regime, load=(0.06, 0.0)
            )
            - nominal_zero,
        }
        references = {
            "load": load_template,
            "mode": mode_template,
            "both": both_template,
        }
        for true_source, signature in signatures.items():
            distances = {
                label: float(np.sqrt(np.mean((signature - reference) ** 2)))
                for label, reference in references.items()
            }
            predicted = min(distances, key=distances.get)
            expected = {
                "load_only": "load",
                "mode_only": "mode",
                "coincident": "both",
            }[true_source]
            ordered = sorted(distances.values())
            rows.append(
                {
                    "regime": regime,
                    "true_source": true_source,
                    "predicted_source": predicted,
                    "correct": predicted == expected,
                    "best_distance": ordered[0],
                    "second_best_distance": ordered[1],
                    "source_margin": ordered[1] - ordered[0],
                    "load_distance": distances["load"],
                    "mode_distance": distances["mode"],
                    "both_distance": distances["both"],
                    "passive_ibr_probe_used": False,
                }
            )
    return rows


def _plot_distance(distance: pd.DataFrame, destination: Path) -> None:
    matrix = pd.DataFrame(0.0, index=REGIMES, columns=REGIMES)
    for row in distance.itertuples(index=False):
        matrix.loc[row.regime_a, row.regime_b] = row.d_ctrl
        matrix.loc[row.regime_b, row.regime_a] = row.d_ctrl
    figure, axis = plt.subplots(figsize=(8, 7))
    image = axis.imshow(matrix.to_numpy(), cmap="viridis", vmin=0.0, vmax=1.0)
    axis.set_xticks(range(len(REGIMES)), REGIMES, rotation=45, ha="right", fontsize=8)
    axis.set_yticks(range(len(REGIMES)), REGIMES, fontsize=8)
    figure.colorbar(image, ax=axis, label="d_ctrl")
    axis.set_title("Control-relevant regime distance")
    figure.tight_layout()
    figure.savefig(destination, dpi=180)
    plt.close(figure)


def _plot_detection(identifiability: pd.DataFrame, destination: Path) -> None:
    summary = (
        identifiability.groupby("event", as_index=False)
        .agg(
            median_detection=("detection_delay_s", "median"),
            Tcritical_s=("Tcritical_s", "first"),
            censored_fraction=("censored", "mean"),
        )
    )
    figure, axis = plt.subplots(figsize=(9, 5))
    positions = np.arange(len(summary))
    axis.bar(positions - 0.2, summary["median_detection"], width=0.4, label="median detection")
    axis.bar(positions + 0.2, summary["Tcritical_s"], width=0.4, label="Tcritical")
    axis.set_xticks(positions, summary["event"], rotation=45, ha="right", fontsize=8)
    axis.set_ylabel("Time after change (s)")
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(destination, dpi=180)
    plt.close(figure)


def _plot_confusion(source: pd.DataFrame, destination: Path) -> None:
    labels = ("load", "mode", "both")
    expected = source["true_source"].map(
        {"load_only": "load", "mode_only": "mode", "coincident": "both"}
    )
    matrix = pd.crosstab(expected, source["predicted_source"]).reindex(
        index=labels, columns=labels, fill_value=0
    )
    figure, axis = plt.subplots(figsize=(5, 4))
    image = axis.imshow(matrix.to_numpy(), cmap="Blues")
    axis.set_xticks(range(3), labels)
    axis.set_yticks(range(3), labels)
    axis.set_xlabel("Predicted source")
    axis.set_ylabel("True source")
    for row in range(3):
        for column in range(3):
            axis.text(column, row, int(matrix.iloc[row, column]), ha="center", va="center")
    figure.colorbar(image, ax=axis)
    figure.tight_layout()
    figure.savefig(destination, dpi=180)
    plt.close(figure)


def main() -> None:
    args = parse_args()
    repository = args.repository.resolve()
    params = load_plant_b_parameters(
        repository / "configs" / "phase_b2_plant_b.yaml", sg_level="scarce"
    )
    result_dir = repository / "results_phase_b2" / "identifiability"
    figure_dir = repository / "figures_phase_b2"
    report_dir = repository / "reports_phase_b2"
    artifact_dir = repository / "artifacts_phase_b2"
    for directory in (result_dir, figure_dir, report_dir, artifact_dir):
        directory.mkdir(parents=True, exist_ok=True)
    distance = pd.DataFrame(
        control_relevant_distance_rows(
            params,
            REGIMES,
            weights=ControlDistanceWeights(
                prediction=0.50,
                action=0.30,
                capability=0.20,
                merge_threshold=0.05,
            ),
        )
    )
    critical_rows: list[dict[str, object]] = []
    identifiability_rows: list[dict[str, object]] = []
    gramian_rows: list[dict[str, object]] = []
    for regime in REGIMES[1:]:
        critical = critical_window(params, actual_regime=regime)
        critical["seed"] = 800
        critical["sg_level"] = "scarce"
        critical_rows.append(critical)
        detection, gramian = passive_detection_rows(
            params,
            actual_regime=regime,
            critical_time_s=float(critical["Tcritical_s"]),
        )
        identifiability_rows.extend(detection)
        gramian_rows.append(gramian)
        print(
            f"audited {regime}: Tcritical={critical['Tcritical_s']}, "
            f"censored={critical['right_censored']}",
            flush=True,
        )
    critical_frame = pd.DataFrame(critical_rows)
    identifiability = pd.DataFrame(identifiability_rows)
    gramian = pd.DataFrame(gramian_rows)
    source = pd.DataFrame(_source_confusion_rows(params))
    coincident_source = source.loc[source["true_source"] == "coincident"].set_index(
        "regime"
    )
    identifiability["regime"] = identifiability["event"].str.replace(
        "nominal_to_", "", regex=False
    )
    identifiability["source_confusion"] = identifiability["regime"].map(
        coincident_source["predicted_source"]
    )
    identifiability["source_confusion_correct"] = identifiability["regime"].map(
        coincident_source["correct"]
    )
    distance.to_csv(result_dir / "control_relevant_regime_distance.csv", index=False)
    critical_frame.to_csv(result_dir / "critical_window.csv", index=False)
    identifiability.to_csv(result_dir / "identifiability.csv", index=False)
    gramian.to_csv(result_dir / "information_gramian.csv", index=False)
    source.to_csv(result_dir / "source_confusion.csv", index=False)
    _plot_distance(distance, figure_dir / "control_relevant_regime_distance.png")
    _plot_detection(identifiability, figure_dir / "detection_vs_Tcritical.png")
    _plot_confusion(source, figure_dir / "source_confusion.png")
    changed = identifiability.loc[~identifiability["Tcritical_s"].isna()]
    before_fraction = float(changed["detected_before_critical"].mean()) if len(changed) else 0.0
    delayed_or_censored_fraction = 1.0 - before_fraction
    control_equivalent_pairs = int(distance["merge_decision"].sum())
    source_accuracy = float(source["correct"].mean())
    decision = {
        "schema_version": "d5freq.phase_b2.identifiability_validation.v1",
        "control_equivalent_pair_count": control_equivalent_pairs,
        "detection_before_Tcritical_fraction": before_fraction,
        "delayed_or_censored_fraction": delayed_or_censored_fraction,
        "source_classification_accuracy": source_accuracy,
        "best_case_detector_uses_same_load_counterfactual": True,
        "active_probe_used": False,
        "thresholds_locked_before_final": True,
    }
    (artifact_dir / "identifiability_validation_lock.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = f"""# Control-Relevant Regime and Passive Identifiability

Physical labels are compared through prediction, candidate-set action and feasible-capability distances. The registered composite is `d_ctrl = 0.5 d_pred + 0.3 d_act + 0.2 d_cap`, with merge threshold `0.05`. The action term uses a finite registered action-set minimizer and is explicitly not a globally optimal action distance. This audit found {control_equivalent_pairs} control-equivalent physical-label pairs.

`Tcritical` is computed separately for each change as the first time a controller using the wrong nominal regime crosses the registered frequency-IAE, control-cost or safety-difference threshold relative to the correct-regime candidate policy. It is not replaced by an arbitrary fixed five-second window. Right-censored windows remain in the table.

Passive detection uses only the response generated by conventional SG action and fixed local plant response; no IBR identification probe is added. The detector is deliberately best-case: it compares the true visible output with a same-load nominal-regime counterfactual initialized from the same evaluation state. Even under this favorable bound, the fraction detected before `Tcritical` is {before_fraction:.3f}; delayed or censored fraction is {delayed_or_censored_fraction:.3f}. A separate load/mode/both signature test gives source accuracy {source_accuracy:.3f}.

These results separate four possibilities: physically different but control-equivalent labels, passive information shortage before control becomes consequential, source confusion between load and regime changes, and structural OOD without an O1 model. They do not authorize an ordinary controller to read true regime, SoC, headroom or future events.
"""
    (report_dir / "06_CONTROL_RELEVANT_IDENTIFIABILITY.md").write_text(
        report, encoding="utf-8"
    )
    print(json.dumps(decision, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
