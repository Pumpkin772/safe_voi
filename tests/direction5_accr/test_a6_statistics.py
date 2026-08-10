from __future__ import annotations

import pandas as pd

import yaml

from scripts.direction5_accr.run_a6_validation import plant_a_manifest, primary_statistics


def test_primary_statistics_preserves_paired_design_cells() -> None:
    methods = (
        "contract_only_recourse_mpc", "accr_mpc",
        "perfect_capability_recourse_oracle",
    )
    rows = []
    for scenario, condition in (("s0", "known"), ("s1", "OOD")):
        for index, method in enumerate(methods):
            rows.append({
                "scenario_id": scenario, "plant": "A_full_nonlinear",
                "mechanism": "power_drop", "sg_tension": "low",
                "period_s": 2.0, "condition": condition, "method": method,
                "frequency_peak_hz": 0.30 - 0.01 * index,
                "ace_iae_pu_s": 2.0 - 0.2 * index,
                "tie_iae_pu_s": 1.0 - 0.1 * index,
                "sg_mechanical_mileage_pu": 0.4 - 0.02 * index,
                "physical_success": True,
            })
    lock = {
        "primary_methods": list(methods),
        "statistics": {
            "materiality_positive_mechanism": "power_drop",
            "bootstrap_resamples": 20,
        },
    }
    paired, result = primary_statistics(pd.DataFrame(rows), lock)
    assert len(paired) == 2
    assert paired.design_cell.nunique() == 1
    assert (paired.relative_improvement_ace_iae_pu_s > 0.0).all()
    assert len(result["rows"]) == 4
    performance = pd.DataFrame(result["rows"]).query("metric in ['ace_iae_pu_s', 'tie_iae_pu_s']")
    assert performance.ci_multiplicity.eq("BONFERRONI_ACE_TIE").all()


def test_validation_manifest_has_explicit_registered_factors() -> None:
    lock = yaml.safe_load(open("configs/direction5_accr/a6_validation_lock.yaml", encoding="utf-8"))
    manifest = plant_a_manifest(lock)
    required = {
        "scenario_id", "split", "seed", "design_cell", "plant",
        "control_period_s", "sg_tension", "capability_mechanism",
        "capability_change_time_s", "load_event_time_s", "load_area",
        "load_sign", "load_magnitude_pu", "initial_soc_area1",
        "initial_soc_area2", "noise_std_hz", "jitter_s",
        "dropout_probability", "probe_eligible", "known_ood",
        "contract_status", "materiality_positive",
    }
    assert required.issubset(manifest.columns)
    assert len(manifest) == 16
    assert manifest.seed.nunique() == 16
    assert (manifest.capability_change_time_s >= 60.0).all()
