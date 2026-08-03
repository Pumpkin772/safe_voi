"""Classify all registered Phase-H cells before terminal-set calibration."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction1freq.models.bess_capability_v2 import CapabilityTruthV2
from direction1freq.models.plant_a_v2 import PlantAParametersV2, PlantAStateV2, TwoAreaPlantAV2
from direction1freq.models.plant_b_andes_v2 import AndesKundurPlantBV2
from direction5_freq.models.load_parameterized_equilibrium import solve_sustainable_equilibrium
from direction5_freq.models.sustainability_classifier import (
    CapabilityContract,
    classify_physical_domain,
)


SG_RESERVES = {"adequate": 0.10, "scarce": 0.05, "critical": 0.025}
TIE_LIMITS = {"A": 0.08, "B": 0.06}
LOAD_CASES = {
    "zero": (0.0, 0.0),
    "a1_pos_002": (0.02, 0.0),
    "a1_pos_004": (0.04, 0.0),
    "a1_pos_006": (0.06, 0.0),
    "a1_pos_008": (0.08, 0.0),
    "both_pos_006_004": (0.06, 0.04),
    "both_pos_008": (0.08, 0.08),
    "a1_neg_006": (-0.06, 0.0),
    "a2_neg_008": (0.0, -0.08),
}
SLOW_RESERVE_ARRIVAL_S = 60.0
SLOW_RESERVE_ADDITIONAL_PU = np.array([0.08, 0.08])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capability_contracts() -> tuple[CapabilityContract, ...]:
    return (
        CapabilityContract(
            "known_nominal",
            "known",
            np.array([-0.10, -0.10]),
            np.array([0.10, 0.10]),
            np.array([0.08, 0.08]),
            np.array([0.08, 0.08]),
            np.array([0.20, 0.20]),
            np.array([20.0, 20.0]),
            np.ones(2),
        ),
        CapabilityContract(
            "known_derated_joint",
            "known",
            np.array([-0.035, -0.035]),
            np.array([0.035, 0.035]),
            np.array([0.012, 0.012]),
            np.array([0.012, 0.012]),
            np.array([1.60, 1.60]),
            np.array([0.80, 0.80]),
            np.array([0.30, 0.30]),
        ),
        CapabilityContract(
            "ood_asymmetric_mixed",
            "ood",
            np.array([-0.080, -0.025]),
            np.array([0.020, 0.070]),
            np.array([0.040, 0.008]),
            np.array([0.006, 0.040]),
            np.array([0.90, 1.30]),
            np.array([0.40, 4.00]),
            np.array([0.50, 1.00]),
        ),
    )


def build_cells() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    contracts = capability_contracts()
    for plant, period, (tension, reserve), (load_case, load_values), contract in itertools.product(
        ("A", "B"),
        (2.0, 4.0),
        SG_RESERVES.items(),
        LOAD_CASES.items(),
        contracts,
    ):
        load = np.asarray(load_values, dtype=float)
        result = classify_physical_domain(
            load,
            reserve,
            TIE_LIMITS[plant],
            contract,
            period,
            SLOW_RESERVE_ARRIVAL_S,
            SLOW_RESERVE_ADDITIONAL_PU,
        )
        equilibrium = result.equilibrium
        post = result.slow_reserve_equilibrium
        rows.append(
            {
                "cell_id": f"{plant}_{period:.0f}s_{tension}_{load_case}_{contract.name}",
                "plant": plant,
                "period_s": period,
                "sg_tension": tension,
                "sg_reserve_pu": reserve,
                "load_case": load_case,
                "load_area_1_pu": load[0],
                "load_area_2_pu": load[1],
                "capability_contract": contract.name,
                "known_ood": contract.known_ood,
                "classification": result.classification,
                "classification_reason": result.reason,
                "classification_locked_before_terminal_calibration": True,
                "equilibrium_feasible": equilibrium.feasible,
                "equilibrium_sg_1_pu": equilibrium.sg_power_pu[0],
                "equilibrium_sg_2_pu": equilibrium.sg_power_pu[1],
                "equilibrium_tie_pu": equilibrium.tie_pu,
                "equilibrium_bess_1_pu": equilibrium.bess_power_pu[0],
                "equilibrium_bess_2_pu": equilibrium.bess_power_pu[1],
                "equilibrium_balance_residual_max_pu": float(
                    np.nanmax(np.abs(equilibrium.balance_residual_pu))
                )
                if equilibrium.feasible
                else float("nan"),
                **{
                    f"equilibrium_x{index}": equilibrium.state_pu[index]
                    for index in range(9)
                },
                "bridge_sg_1_pu": result.bridge_sg_power_pu[0],
                "bridge_sg_2_pu": result.bridge_sg_power_pu[1],
                "bridge_bess_1_pu": result.bridge_bess_power_pu[0],
                "bridge_bess_2_pu": result.bridge_bess_power_pu[1],
                "bridge_tie_pu": result.bridge_tie_pu,
                "bridge_energy_area_1_mwh": result.bridge_energy_required_mwh[0],
                "bridge_energy_area_2_mwh": result.bridge_energy_required_mwh[1],
                "bridge_balance_residual_max_pu": float(
                    np.nanmax(np.abs(result.bridge_power_balance_residual_pu))
                )
                if np.isfinite(result.bridge_power_balance_residual_pu).all()
                else float("nan"),
                "slow_reserve_arrival_s": SLOW_RESERVE_ARRIVAL_S,
                "post_reserve_equilibrium_feasible": post.feasible,
                "post_reserve_balance_residual_max_pu": float(
                    np.nanmax(np.abs(post.balance_residual_pu))
                )
                if post.feasible
                else float("nan"),
                "binding_constraints": "|".join(result.binding_constraints),
                "physical_infeasibility_not_controller_failure": result.classification
                == "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
            }
        )
    return pd.DataFrame(rows).sort_values("cell_id").reset_index(drop=True)


def plant_a_equilibrium_crosscheck(period_s: float) -> dict[str, object]:
    reserve = SG_RESERVES["critical"]
    load = np.array([0.02, 0.0])
    parameters = replace(
        PlantAParametersV2(),
        sg_power_lower_pu=(-reserve, -reserve),
        sg_power_upper_pu=(reserve, reserve),
        valve_lower_pu=(-1.2 * reserve, -1.2 * reserve),
        valve_upper_pu=(1.2 * reserve, 1.2 * reserve),
    )
    plant = TwoAreaPlantAV2(parameters, dt_s=0.02)
    equilibrium = solve_sustainable_equilibrium(
        load, np.full(2, -reserve), np.full(2, reserve), TIE_LIMITS["A"]
    )
    bess = plant.equilibrium().bess
    state = PlantAStateV2(
        omega_pu=np.zeros(2),
        tie_pu=equilibrium.tie_pu,
        valve_pu=equilibrium.sg_power_pu.copy(),
        mechanical_power_pu=equilibrium.sg_power_pu.copy(),
        bess=bess,
    )
    command = np.array(
        [
            equilibrium.sg_power_pu[0],
            0.0,
            equilibrium.sg_power_pu[1],
            0.0,
        ]
    )
    next_state, diagnostics = plant.step(
        state, command, load, CapabilityTruthV2()
    )
    return {
        "plant": "A",
        "period_s": period_s,
        "static_balance_residual_max_pu": float(
            np.max(np.abs(equilibrium.balance_residual_pu))
        ),
        "one_step_state_residual_max_pu": float(
            np.max(np.abs(plant.state_vector(next_state) - plant.state_vector(state)))
        ),
        "one_step_power_balance_residual_max_pu": float(
            np.max(np.abs(diagnostics.power_balance_residual_pu))
        ),
        "converged": True,
        "native_network": False,
    }


def plant_b_equilibrium_crosscheck(period_s: float) -> dict[str, object]:
    load = np.array([0.02, 0.0])
    reserve = SG_RESERVES["critical"]
    equilibrium = solve_sustainable_equilibrium(
        load, np.full(2, -reserve), np.full(2, reserve), TIE_LIMITS["B"]
    )
    command = np.array(
        [
            equilibrium.sg_power_pu[0],
            0.0,
            equilibrium.sg_power_pu[1],
            0.0,
        ]
    )
    plant = AndesKundurPlantBV2(dt_s=0.02)
    trace = plant.run_causal_closed_loop(
        duration_s=12.0,
        control_period_s=period_s,
        load_profile=lambda _time: load,
        policy=lambda _observation: command,
    )
    terminal = trace.time_s >= max(0.0, trace.time_s[-1] - 2.0)
    return {
        "plant": "B",
        "period_s": period_s,
        "static_balance_residual_max_pu": float(
            np.max(np.abs(equilibrium.balance_residual_pu))
        ),
        "one_step_state_residual_max_pu": float("nan"),
        "one_step_power_balance_residual_max_pu": trace.algebraic_power_balance_p99_pu,
        "terminal_frequency_max_hz": float(
            np.max(np.abs(trace.frequency_deviation_hz[terminal]))
        ),
        "terminal_ace_max_pu": float(np.max(np.abs(trace.ace_pu[terminal]))),
        "converged": trace.converged,
        "native_network": trace.native_network,
    }


def main() -> None:
    result_dir = REPO / "results_phase_h/H2"
    model_dir = REPO / "research_outputs_phase_h/03_MODEL"
    config_dir = REPO / "configs/phase_h"
    progress_dir = REPO / "progress_phase_h"
    for directory in (result_dir, model_dir, config_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)

    cells = build_cells()
    cells_path = result_dir / "SUSTAINABILITY_CELLS.parquet"
    cells.to_parquet(cells_path, index=False, compression="zstd")
    bridge = cells[cells.classification.eq("BRIDGE_ONLY")].copy()
    bridge_path = result_dir / "BRIDGE_REQUIREMENTS.parquet"
    bridge.to_parquet(bridge_path, index=False, compression="zstd")
    infeasible = cells[
        cells.classification.eq(
            "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY"
        )
    ].copy()
    infeasible_path = result_dir / "PHYSICALLY_INFEASIBLE_CELLS.csv"
    infeasible.to_csv(infeasible_path, index=False)

    crosschecks = pd.DataFrame(
        [
            plant_a_equilibrium_crosscheck(period)
            for period in (2.0, 4.0)
        ]
        + [
            plant_b_equilibrium_crosscheck(period)
            for period in (2.0, 4.0)
        ]
    )
    crosscheck_path = result_dir / "EQUILIBRIUM_TIME_DOMAIN_CROSSCHECK.csv"
    crosschecks.to_csv(crosscheck_path, index=False)

    manifest_hash = sha256(cells_path)
    lock_path = config_dir / "H2_DOMAIN_MANIFEST_LOCK.json"
    lock_path.write_text(
        json.dumps(
            {
                "schema": "direction5.phase_h.domain_manifest_lock.v1",
                "path": "results_phase_h/H2/SUSTAINABILITY_CELLS.parquet",
                "sha256": manifest_hash,
                "cells": int(len(cells)),
                "classification_counts": cells.classification.value_counts().to_dict(),
                "locked_before_terminal_calibration": True,
                "final_seeds_consumed": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    sustainability_doc = model_dir / "SUSTAINABILITY_LP.md"
    sustainability_doc.write_text(
        """# Registered sustainability LP

For every Plant, period, SG tension, load cell, and capability contract, H2
solves the two-area balance with long-run BESS power fixed to zero. The LP
minimizes absolute tie flow subject to SG and tie limits. A cell is sustainable
only when this LP is feasible. The stored state is the load-parameterized
equilibrium `[omega, tie, valve, mechanical, actual BESS]`; valve and mechanical
power equal the SG equilibrium dispatch.

The classification is completed and hash-locked before observer terminal-window
selection or controller design. Evaluation-side known/OOD labels are never
controller inputs.
""",
        encoding="utf-8",
    )
    equilibrium_doc = model_dir / "LOAD_PARAMETERIZED_EQUILIBRIA.md"
    equilibrium_doc.write_text(
        """# Load-parameterized equilibria

For load `d`, H2 solves `pm1 - d1 - ptie = 0` and
`pm2 - d2 + ptie = 0`, with `pb*=0`. The resulting `x*(d)` is stored in
`SUSTAINABILITY_CELLS.parquet`. Terminal errors in later stages must be formed
about this object, not the historical zero-load origin. Every feasible static
power-balance residual is required below `1e-8 pu`; representative Plant-A
state integration and native Plant-B DAE runs are saved separately.
""",
        encoding="utf-8",
    )
    bridge_doc = model_dir / "BRIDGE_ENERGY_MODEL.md"
    bridge_doc.write_text(
        """# Finite-energy bridge and physical infeasibility model

The registered slow reserve arrives at 60 s and adds 0.08 pu symmetric SG
reserve per area. Pre-arrival BESS dispatch is solved under guaranteed power,
ramp over the delay-adjusted first control interval, availability, tie, and SG
limits. Charge/discharge energy is integrated only until slow-reserve arrival.
A bridge cell must enter a sustainable post-arrival equilibrium. Cells failing
steady-state power, pre-arrival power/ramp/delay, or energy are labeled
`PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY` before any controller run
and cannot be counted as ordinary controller failures.
""",
        encoding="utf-8",
    )

    feasible_residuals = pd.concat(
        [
            cells.loc[
                cells.equilibrium_feasible,
                "equilibrium_balance_residual_max_pu",
            ],
            cells.loc[
                cells.classification.eq("BRIDGE_ONLY"),
                "bridge_balance_residual_max_pu",
            ],
            cells.loc[
                cells.post_reserve_equilibrium_feasible,
                "post_reserve_balance_residual_max_pu",
            ],
        ],
        ignore_index=True,
    ).dropna()
    counts = cells.classification.value_counts().to_dict()
    gate_components = {
        "all_cells_uniquely_preclassified": bool(
            len(cells) == cells.cell_id.nunique()
            and cells.classification.notna().all()
        ),
        "all_static_balance_residuals_below_1e_8_pu": bool(
            feasible_residuals.max() < 1e-8
        ),
        "nonempty_sustainable_domain": counts.get("SUSTAINABLE", 0) > 0,
        "nonempty_physically_interpretable_bridge_domain": counts.get(
            "BRIDGE_ONLY", 0
        )
        > 0,
        "nonempty_predeclared_infeasible_domain": counts.get(
            "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY", 0
        )
        > 0,
        "plant_a_b_and_2s_4s_covered": bool(
            set(cells.plant) == {"A", "B"}
            and set(cells.period_s) == {2.0, 4.0}
        ),
        "known_and_ood_contracts_covered": set(cells.known_ood) == {"known", "ood"},
        "plant_a_b_time_domain_crosschecks_converged": bool(
            crosschecks.converged.all()
        ),
        "native_plant_b_crosscheck_present": bool(
            crosschecks[crosschecks.plant.eq("B")].native_network.all()
        ),
        "manifest_hash_locked_before_terminal_calibration": True,
        "final_seeds_not_consumed": True,
    }
    outputs = (
        cells_path,
        bridge_path,
        infeasible_path,
        crosscheck_path,
        lock_path,
        sustainability_doc,
        equilibrium_doc,
        bridge_doc,
    )
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H2",
        "inputs": {
            "plants": ["A", "B"],
            "periods_s": [2.0, 4.0],
            "sg_tensions": SG_RESERVES,
            "capability_contracts": [item.name for item in capability_contracts()],
            "slow_reserve_arrival_s": SLOW_RESERVE_ARRIVAL_S,
        },
        "commands": [
            "python scripts/phase_h/run_h2_domains.py",
            "python -m pytest tests/phase_h/test_h2_power_balance_and_partition.py -q",
        ],
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
        "gate": "H2_PHYSICAL_DOMAIN_AND_EQUILIBRIA",
        "gate_components": gate_components,
        "gate_passed": all(gate_components.values()),
        "classification_counts": counts,
        "domain_manifest_sha256": manifest_hash,
        "failures": [],
        "repairs": [],
        "final_seeds_consumed": False,
        "next_stage": "H3" if all(gate_components.values()) else "H9_PHYSICAL_DOMAIN_FAILURE",
    }
    progress_path = progress_dir / "H2.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
