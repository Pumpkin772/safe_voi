from __future__ import annotations

import inspect
import json
from pathlib import Path

import pandas as pd

from direction5freq.estimation.deliverability_set_mhe import DeliverabilitySetMHE
from direction5freq.estimation.grid_load_observer import GridLoadObserver, LoadObserverInput


REPO = Path(__file__).resolve().parents[2]


def test_selected_load_observer_api_requires_actual_poi_and_has_no_command_or_truth() -> None:
    fields = set(LoadObserverInput.__dataclass_fields__)
    assert "bess_actual_poi_power_pu" in fields
    assert "issued_command_pu" not in fields
    assert "true_load" not in fields
    source = inspect.getsource(GridLoadObserver.update)
    assert "bess_actual_poi_power_pu" in source


def test_deliverability_estimator_scope_is_power_ramp_delay_and_no_excitation_is_wide() -> None:
    source = inspect.getsource(DeliverabilitySetMHE)
    assert "delay_interval" in source
    assert "ramp_up" in source
    assert "energy" not in source.lower()
    assert "availability" not in source.lower()
    audit = pd.read_csv(REPO / "results_phase_i/I3/NO_EXCITATION_AUDIT.csv")
    assert (~audit.excitation_sufficient).all()
    assert audit.delay_width0_s.ge(1.45).all()
    assert audit.power_width0_pu.ge(0.095).all()


def test_i3_reports_finite_sample_coverage_and_false_optimism() -> None:
    coverage = pd.read_csv(REPO / "results_phase_i/I3/COVERAGE_SUMMARY.csv")
    delay = coverage[coverage.metric.eq("delay_covered")].iloc[0]
    optimism = coverage[coverage.metric.eq("false_optimism")].iloc[0]
    assert delay.samples >= 60
    assert delay.empirical_coverage >= 0.95
    assert delay.one_sided_95_confidence_lower > 0.0
    assert optimism.empirical_coverage <= 0.01
    for field in ("plant", "period_s", "horizon_s"):
        assert coverage[field].notna().all()


def test_i3_contract_floor_and_online_envelope_have_distinct_semantics() -> None:
    audit = pd.read_csv(REPO / "results_phase_i/I3/CONTRACT_FLOOR_AUDIT.csv")
    within = audit[audit.case.eq("within_contract")].iloc[0]
    violation = audit[audit.case.eq("contract_violation")].iloc[0]
    assert bool(within.truth_contains_contract)
    assert not bool(violation.truth_contains_contract)
    assert violation.detector_status_after_evidence == "DETECTED_CONTRACT_VIOLATION"
    assert audit.hard_safety_source.eq("contract_floor").all()
    assert not audit.online_envelope_safety_source.all()


def test_i3_gate_and_selected_estimators_are_locked() -> None:
    progress = json.loads((REPO / "progress_phase_i/I3.json").read_text("utf-8"))
    assert progress["gate_passed"]
    assert progress["selected_observer"] == "ACTUAL_POI_AUGMENTED_SLOW_LOAD_STATE"
    assert progress["selected_capability_estimator"] == "CAUSAL_SET_MEMBERSHIP_MHE_P_R_DELAY"
    assert not progress["final_seeds_consumed"]
