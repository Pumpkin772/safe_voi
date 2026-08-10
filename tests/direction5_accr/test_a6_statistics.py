from __future__ import annotations

import pandas as pd

from scripts.direction5_accr.run_a6_validation import primary_statistics


def test_primary_statistics_preserves_paired_design_cells() -> None:
    methods = (
        "contract_only_recourse_mpc", "accr_mpc",
        "perfect_capability_recourse_oracle",
    )
    rows = []
    for scenario in ("s0", "s1"):
        for index, method in enumerate(methods):
            rows.append({
                "scenario_id": scenario, "plant": "A_full_nonlinear",
                "mechanism": "power_drop", "sg_tension": "low",
                "period_s": 2.0, "condition": "known", "method": method,
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
    assert (paired.relative_improvement_ace_iae_pu_s > 0.0).all()
    assert len(result["rows"]) == 4
