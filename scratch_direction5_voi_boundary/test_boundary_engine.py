from __future__ import annotations

import numpy as np
import pandas as pd

from voi_boundary_engine import (
    BoundaryPoint,
    candidate_models,
    enumerate_possible_posteriors,
    normalized_probe_sequence,
    objective_scales,
    probe_library,
    solve_policy,
)
from selective_boundary_policy import CausalBoundaryFeatures, FrozenBoundaryLookup, SelectiveProbeScheduler


def point(**changes) -> BoundaryPoint:
    values = dict(
        point_id="test", period_s=2.0, sg_tension="medium",
        load_magnitude_pu=0.045, power_spread_pu=0.035,
        ramp_spread_pu_per_s=0.035, delay_spread_s=1.3,
        noise_std_pu=0.001, soc=0.5, tie_loading_pu=0.02,
    )
    values.update(changes)
    return BoundaryPoint(**values)


def test_complete_vertex_set_and_degenerate_set() -> None:
    models = candidate_models(point())
    assert len(models) == 8
    assert {item.power_pu for item in models} == {0.045, 0.080}
    assert {item.ramp_pu_per_s for item in models} == {0.025, 0.060}
    assert {item.delay_s for item in models} == {0.20, 1.50}
    assert len(candidate_models(point(
        power_spread_pu=0.0, ramp_spread_pu_per_s=0.0, delay_spread_s=0.0
    ))) == 1


def test_probe_physical_duration_and_allocation_integral() -> None:
    for period in (2.0, 4.0):
        probes = probe_library(point(period_s=period))
        assert probes
        for probe in probes:
            assert len(probe.sequence_pu) * period == probe.duration_s
            assert abs(sum(probe.sequence_pu) * period) <= 1e-12
            assert max(abs(item) for item in probe.sequence_pu) <= probe.amplitude_pu + 1e-12
    assert normalized_probe_sequence((1.0, -1.0), 1) is None


def test_all_scalar_interval_posteriors_are_enumerated() -> None:
    posteriors = enumerate_possible_posteriors({
        "a": (-1.0, 0.25), "b": (-0.25, 1.0), "c": (2.0, 3.0),
    })
    assert ("a",) in posteriors
    assert ("b",) in posteriors
    assert ("a", "b") in posteriors
    assert ("c",) in posteriors
    assert all(item for item in posteriors)


def test_every_objective_keeps_frequency_ace_and_tie_nonzero() -> None:
    for name in ("balanced", "regional_responsibility", "resource_economy"):
        scales = objective_scales(name)
        values = np.array((scales.frequency_hz, scales.ace_pu, scales.tie_pu))
        assert np.all(np.isfinite(values))
        assert np.all(values > 0.0)


def test_zero_region_returns_identical_contract_action_object(tmp_path) -> None:
    rows = []
    for index in range(5):
        row = point(point_id=f"z{index}")
        payload = {name: getattr(row, name) for name in row.__dataclass_fields__}
        payload.update(region="ZERO_VALUE_PROVED", solver_failures=0,
                       maximum_exact_probe_value=-0.1, selected_probe_id=None)
        rows.append(payload)
    map_path = tmp_path / "map.csv"
    pd.DataFrame(rows).to_csv(map_path, index=False)
    lookup = FrozenBoundaryLookup(map_path, tmp_path, neighbors=5)
    scheduler = SelectiveProbeScheduler(lookup)
    features = CausalBoundaryFeatures(
        period_s=2.0, sg_tension="medium", objective="balanced",
        load_magnitude_pu=0.045, power_spread_pu=0.035,
        ramp_spread_pu_per_s=0.035, delay_spread_s=1.3,
        noise_std_pu=0.001, soc=0.5, tie_loading_pu=0.02,
    )
    decision = scheduler.consider(features, causal_change_epoch=1, decision_relevant=True)
    assert not decision.worthwhile
    action = np.array((0.01, 0.02, 0.03, 0.04))
    assert scheduler.overlay(action) is action


def test_rolling_policy_uses_signed_causal_area_load_forecast() -> None:
    item = point(period_s=4.0)
    models = candidate_models(item)
    signed = solve_policy(
        item, models, horizon_steps=6, initial_grid_state=np.zeros(7),
        load_forecast_pu=np.array((-0.02, 0.01)),
    )
    legacy_unsigned = solve_policy(
        item, models, horizon_steps=6, initial_grid_state=np.zeros(7),
    )
    assert np.isfinite(signed.objective)
    assert signed.sg_command[0, 0] < 0.0
    assert signed.bess_command[0, 0] < 0.0
    assert legacy_unsigned.sg_command[0, 0] > 0.0
    assert legacy_unsigned.bess_command[0, 0] > 0.0
