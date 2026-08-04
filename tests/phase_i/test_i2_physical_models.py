from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from direction5freq.models.capability_contract import (
    BESSParameters,
    CapabilityRealization,
)
from direction5freq.models.plant_a_full import PlantAFull
from direction5freq.models.plant_b_andes_full import PlantBAndesFull


REPO = Path(__file__).resolve().parents[2]


def test_phase_i_models_do_not_import_historical_phase_packages() -> None:
    for module in (
        REPO / "src/direction5freq/models/capability_contract.py",
        REPO / "src/direction5freq/models/plant_a_full.py",
        REPO / "src/direction5freq/models/plant_b_andes_full.py",
    ):
        source = module.read_text("utf-8")
        assert "direction1freq" not in source
        assert "direction5_freq" not in source


def test_hidden_truth_contains_no_energy_or_availability_dimension() -> None:
    fields = set(CapabilityRealization.__dataclass_fields__)
    assert fields == {
        "lower_power_pu", "upper_power_pu",
        "ramp_down_pu_per_s", "ramp_up_pu_per_s", "delay_s",
    }
    assert BESSParameters().energy_mwh > 0.0


def test_full_plant_a_uses_measured_soc_actual_power_and_slow_reserve() -> None:
    plant = PlantAFull(dt_s=0.02)
    state = plant.equilibrium()
    state, diagnostics = plant.step(
        state,
        np.array((0.0, 0.04, 0.0, 0.0)),
        np.array((0.02, 0.0)),
        CapabilityRealization(),
        np.array((0.05, 0.0)),
    )
    observation = plant.public_observation(0.02, state, np.zeros(4))
    assert observation.bess_actual_power_pu.shape == (2,)
    assert np.allclose(observation.measured_soc, state.bess.energy_mwh / plant.parameters.bess.energy_mwh)
    assert state.slow_reserve.power_pu[0] > 0.0
    assert np.max(np.abs(diagnostics.power_balance_residual_pu)) <= 1e-10


def test_i2_outputs_prove_native_b_and_real_normal_hour() -> None:
    crosscheck = pd.read_csv(REPO / "results_phase_i/I2/PLANT_A_B_CROSSCHECK.csv")
    native = crosscheck[crosscheck.plant.str.startswith("B_")].iloc[0]
    assert bool(native.native_network)
    assert bool(native.converged)
    assert bool(native.initialization_diagnostic_enabled)
    normal = json.loads((REPO / "results_phase_i/I2/NORMAL1H_PROVENANCE.json").read_text("utf-8"))
    assert normal["physical_steps"] == 180000
    assert normal["trajectory_rows"] == 1801
    assert not normal["all_zero_load"]
    assert normal["artificial_rows"] == 0


def test_i2_event_manifest_has_independent_factors_and_full_horizons() -> None:
    manifest = pd.read_csv(REPO / "results_phase_i/I2/CORE_EVENT_MANIFEST.csv")
    assert set(manifest.mechanism) == {"power_drop", "ramp_drop", "delay_increase"}
    assert set(manifest.sg_tension) == {"low", "high"}
    assert set(manifest.period_s) == {2.0, 4.0}
    assert manifest.duration_s.isin([300.0, 600.0]).all()
    assert manifest.nominal_warmup_s.ge(60.0).all()
    assert manifest.capability_change_time_s.nunique() == len(manifest)
    assert not np.allclose(manifest.capability_change_time_s, manifest.load_event_time_s)
    assert manifest.controller_updates_entire_horizon.all()


def test_i2_gate_passes_without_surrogate_or_artificial_rows() -> None:
    progress = json.loads((REPO / "progress_phase_i/I2.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["plant_a"] == "FULL_NONLINEAR_RK4"
    assert progress["plant_b"] == "NATIVE_ANDES_KUNDUR_RMS_DAE"
    assert not progress["final_seeds_consumed"]
