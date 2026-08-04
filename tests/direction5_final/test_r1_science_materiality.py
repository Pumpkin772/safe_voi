from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from direction5freq.controllers.dcsv_mpc_final import DCSVInput
from direction5freq.controllers.domain_supervisor import DomainSupervisor
from direction5freq.controllers.oracle_mpc import TrueCapabilityOracleMPC
from direction5freq.estimation.deliverability_set_mhe import DeliverabilitySetMHE
from direction5freq.models.plant_a_full import PlantAFull


REPO = Path(__file__).resolve().parents[2]


def test_oracle_truth_api_is_explicitly_evaluation_only() -> None:
    plant = PlantAFull()
    observation = plant.public_observation(0.0, plant.equilibrium(), np.zeros(4))
    envelope = DeliverabilitySetMHE(plant.parameters.bess.contract, 2.0).update(
        0.0, np.zeros(2), np.zeros(2)
    )
    domain = DomainSupervisor(plant.parameters).classify(np.zeros(2), observation.measured_soc)
    inputs = DCSVInput(observation, np.zeros(2), envelope, domain)
    oracle = TrueCapabilityOracleMPC(2.0, horizon_steps=2)
    assert oracle.evaluation_only
    with pytest.raises(RuntimeError, match="evaluation-only"):
        oracle.propose(inputs)


def test_r1_registry_and_materiality_outputs_meet_locked_scope() -> None:
    registry = pd.read_csv(REPO / "research_outputs_final/02_LITERATURE/CORE_LITERATURE_REGISTRY.csv")
    assert len(registry) >= 60
    assert not registry.covers_complete_dcsv_intersection.astype(str).str.lower().eq("true").any()
    materiality = pd.read_csv(REPO / "research_outputs_final/11_SUMMARY_TABLES/R1/MATERIALITY_BY_MECHANISM.csv")
    assert set(materiality.mechanism) == {"power_drop", "ramp_drop", "delay_increase"}
    assert set(materiality.sg_tension) == {"low", "high"}
    assert materiality.groupby("mechanism").material_value.all().sum() >= 2
    assert (materiality.groupby("sg_tension").material_value.sum() >= 2).all()


def test_r1_manifest_has_independent_events_and_no_final_seeds() -> None:
    manifest = pd.read_csv(REPO / "results_final/R1/MATERIALITY_MANIFEST.csv")
    assert manifest.split.eq("development").all()
    assert manifest.seed.between(0, 29).all()
    assert (manifest.capability_change_time_s >= 60.0).all()
    assert (manifest.load_event_time_s >= 60.0).all()
    assert not np.allclose(manifest.capability_change_time_s, manifest.load_event_time_s)

