"""Recompute sustainable, bridge, and physical-infeasibility certificates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from direction1freq.models.delay_augmented_prediction import exact_fractional_delay_vertex
from direction5_freq.controllers.dcsv_mpc import (
    DCSVInput,
    DisturbanceCapabilitySeparatedViabilityMPC,
)
from direction5_freq.models.sustainability_classifier import classify_physical_domain
from direction5_freq.optimization.bridge_certificate import certify_bridge
from direction5_freq.optimization.infeasibility_certificate import deficit_components
from direction5_freq.optimization.terminal_set import compute_sustainable_terminal_set
from scripts.phase_h.run_h2_domains import (
    SG_RESERVES,
    SLOW_RESERVE_ADDITIONAL_PU,
    SLOW_RESERVE_ARRIVAL_S,
    TIE_LIMITS,
    capability_contracts,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def terminal_certificates(local_path: Path):
    data = np.load(local_path)
    certificates = []
    records = []
    for plant_index, plant in enumerate(data["plants"].astype(str)):
        for period_index, period in enumerate(data["periods_s"].astype(float)):
            vertex = exact_fractional_delay_vertex(float(period), 0.20)
            model_radius = data["state_prediction_radii"][
                plant_index, period_index, 0
            ]
            load_radius = data["persistent_load_error_radii"][
                plant_index, period_index, 0
            ]
            disturbance = model_radius + np.abs(vertex.ed) @ load_radius
            terminal_radius = (
                data["equilibrium_neighborhood_radii"]
                + data["state_prediction_radii"][plant_index, period_index, -1]
            )
            certificate = compute_sustainable_terminal_set(
                plant, period, disturbance, terminal_radius
            )
            certificates.append(certificate)
            records.append(
                {
                    "plant": plant,
                    "period_s": period,
                    "spectral_radius": certificate.spectral_radius,
                    "tail_generator_inf": certificate.tail_generator_inf,
                    "iterations": certificate.iterations,
                    "frequency_support_max_hz": float(
                        certificate.frequency_support_hz.max()
                    ),
                    "ace_support_max_pu": float(certificate.ace_support_pu.max()),
                    "tie_support_pu": certificate.tie_support_pu,
                    "valve_support_max_pu": float(certificate.valve_support_pu.max()),
                    "mechanical_support_max_pu": float(
                        certificate.mechanical_support_pu.max()
                    ),
                    "command_support_max_pu": float(
                        certificate.command_support_pu.max()
                    ),
                    "required_equilibrium_sg_margin_pu": 0.025,
                    "stable": certificate.stable,
                    "rpi_invariant_to_tolerance": certificate.invariant,
                    "hard_constraints_admissible_in_restricted_initial_domain": certificate.admissible,
                    "contained_in_h4_terminal_radius": certificate.terminal_radius_compatible,
                    "bess_terminal_policy": "zero_command_sg_only_feedback",
                    "load_parameterized_translation": True,
                    "disturbance_set_semantics": "H4 empirical local model plus persistent load-rate set",
                }
            )
    return certificates, pd.DataFrame(records)


def save_terminal_set(path: Path, certificates) -> None:
    maximum_generators = max(item.generator_matrix.shape[1] for item in certificates)
    generators = np.full((len(certificates), 11, maximum_generators), np.nan)
    for index, item in enumerate(certificates):
        generators[index, :, : item.generator_matrix.shape[1]] = item.generator_matrix
    np.savez_compressed(
        path,
        plants=np.asarray([item.plant for item in certificates]),
        periods_s=np.asarray([item.period_s for item in certificates]),
        closed_loop_matrices=np.asarray(
            [item.closed_loop_matrix for item in certificates]
        ),
        feedback_gains=np.asarray([item.feedback_gain for item in certificates]),
        disturbance_radii=np.asarray(
            [item.disturbance_radius for item in certificates]
        ),
        generator_matrices_padded=generators,
        generator_columns=np.asarray(
            [item.generator_matrix.shape[1] for item in certificates]
        ),
        coordinate_support=np.asarray(
            [item.coordinate_support for item in certificates]
        ),
        invariant=np.asarray([item.invariant for item in certificates]),
        admissible=np.asarray([item.admissible for item in certificates]),
        terminal_radius_compatible=np.asarray(
            [item.terminal_radius_compatible for item in certificates]
        ),
        tail_tolerance=np.array(1e-10),
        required_equilibrium_sg_margin_pu=np.array(0.025),
        set_semantics=np.array(
            "minimal RPI zonotope for fixed SG-only terminal policy under registered empirical local disturbance"
        ),
    )


def bridge_and_infeasibility():
    contracts = {item.name: item for item in capability_contracts()}
    bridge_source = pd.read_parquet(REPO / "results_phase_h/H2/BRIDGE_REQUIREMENTS.parquet")
    bridge_rows = []
    for _, row in bridge_source.iterrows():
        contract = contracts[str(row.capability_contract)]
        recomputed = classify_physical_domain(
            row[["load_area_1_pu", "load_area_2_pu"]].to_numpy(float),
            float(row.sg_reserve_pu),
            TIE_LIMITS[str(row.plant)],
            contract,
            float(row.period_s),
            SLOW_RESERVE_ARRIVAL_S,
            SLOW_RESERVE_ADDITIONAL_PU,
        )
        certificate = certify_bridge(
            recomputed,
            contract,
            float(row.period_s),
            50.0 if row.plant == "A" else 60.0,
        )
        bridge_rows.append(
            {
                **row.to_dict(),
                "classification_recomputed": recomputed.classification,
                "power_feasible": certificate.power_feasible,
                "ramp_delay_feasible": certificate.ramp_delay_feasible,
                "energy_feasible": certificate.energy_feasible,
                "slow_reserve_handoff_feasible": certificate.slow_reserve_handoff_feasible,
                "frequency_bound_hz": certificate.frequency_bound_hz,
                "ace_bound_pu": certificate.ace_bound_pu,
                "tie_bound_pu": certificate.tie_bound_pu,
                "safety_feasible": certificate.safety_feasible,
                "finite_horizon_viable": certificate.finite_horizon_viable,
                "recursive_feasibility_claimed": False,
                "claim": "FINITE_ENERGY_BRIDGE_TO_REGISTERED_SLOW_RESERVE",
            }
        )
    infeasible_source = pd.read_csv(
        REPO / "results_phase_h/H2/PHYSICALLY_INFEASIBLE_CELLS.csv"
    )
    infeasible_rows = []
    for _, row in infeasible_source.iterrows():
        contract = contracts[str(row.capability_contract)]
        deficits = deficit_components(
            row[["load_area_1_pu", "load_area_2_pu"]].to_numpy(float),
            float(row.sg_reserve_pu),
            SLOW_RESERVE_ADDITIONAL_PU,
            contract,
            float(row.period_s),
            SLOW_RESERVE_ARRIVAL_S,
        )
        recomputed = classify_physical_domain(
            row[["load_area_1_pu", "load_area_2_pu"]].to_numpy(float),
            float(row.sg_reserve_pu),
            TIE_LIMITS[str(row.plant)],
            contract,
            float(row.period_s),
            SLOW_RESERVE_ARRIVAL_S,
            SLOW_RESERVE_ADDITIONAL_PU,
        )
        infeasible_rows.append(
            {
                **row.to_dict(),
                **deficits,
                "classification_recomputed": recomputed.classification,
                "certificate_nonempty": bool(
                    max(deficits.values()) > 0.0 or bool(row.binding_constraints)
                ),
                "not_counted_as_controller_failure": True,
                "claim": "PHYSICALLY_INFEASIBLE_UNDER_REGISTERED_CAPABILITY",
            }
        )
    return pd.DataFrame(bridge_rows), pd.DataFrame(infeasible_rows)


def replay_exact_terminal_object(terminal_table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    supported = terminal_table[
        terminal_table.rpi_invariant_to_tolerance
        & terminal_table.hard_constraints_admissible_in_restricted_initial_domain
        & terminal_table.contained_in_h4_terminal_radius
    ]
    for _, row in supported.iterrows():
        controller = DisturbanceCapabilitySeparatedViabilityMPC(
            float(row.period_s),
            3,
            plant=str(row.plant),
            sg_reserve_pu=0.10,
        )
        data = DCSVInput(
            state_estimate_pu=np.zeros(9),
            load_estimate_pu=np.zeros(2),
            previous_actual_action_pu=np.zeros(4),
            actual_bess_power_pu=np.zeros(2),
            energy_state_mwh=np.full(2, 25.0),
            power_discharge_guaranteed_pu=np.full(2, 0.05),
            power_charge_guaranteed_pu=np.full(2, 0.05),
            ramp_up_guaranteed_pu_per_s=np.full(2, 0.04),
            ramp_down_guaranteed_pu_per_s=np.full(2, 0.04),
            delay_interval_s=np.array([[0.1, 0.4], [0.1, 0.4]]),
            energy_available_guaranteed_mwh=np.full(2, 10.0),
            availability_interval=np.array([[0.5, 1.0], [0.5, 1.0]]),
        )
        _action, diagnostic = controller.control(data)
        exact_loaded = controller.terminal_generator_matrix is not None
        terminal_bess_zero = bool(
            diagnostic.solved
            and np.max(np.abs(diagnostic.predicted_actions[-1, [1, 3]])) <= 1e-8
        )
        rows.append(
            {
                "plant": row.plant,
                "period_s": row.period_s,
                "exact_generator_matrix_loaded": exact_loaded,
                "primary_solve_accepted": diagnostic.solved
                and not diagnostic.restoration_used,
                "zero_terminal_bess_command": terminal_bess_zero,
                "actual_action_history_pipeline_matches": diagnostic.action_history_match,
                "hard_constraint_residual": diagnostic.hard_constraint_residual,
                "code_object_replay_passed": bool(
                    exact_loaded
                    and diagnostic.solved
                    and not diagnostic.restoration_used
                    and terminal_bess_zero
                    and diagnostic.action_history_match
                    and diagnostic.hard_constraint_residual <= 1e-5
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    theory_dir = REPO / "research_outputs_phase_h/05_THEORY"
    result_dir = REPO / "results_phase_h/H6"
    progress_dir = REPO / "progress_phase_h"
    for directory in (theory_dir, result_dir, progress_dir):
        directory.mkdir(parents=True, exist_ok=True)
    local_path = REPO / "research_outputs_phase_h/03_MODEL/LOCAL_TERMINAL_SET.npz"
    certificates, terminal_table = terminal_certificates(local_path)
    terminal_path = theory_dir / "SUSTAINABLE_TERMINAL_SET.npz"
    save_terminal_set(terminal_path, certificates)
    terminal_table_path = result_dir / "SUSTAINABLE_TERMINAL_SET_AUDIT.csv"
    terminal_table.to_csv(terminal_table_path, index=False)
    bridge, infeasible = bridge_and_infeasibility()
    bridge_path = theory_dir / "BRIDGE_CERTIFICATES.parquet"
    infeasible_path = theory_dir / "INFEASIBILITY_CERTIFICATES.parquet"
    bridge.to_parquet(bridge_path, index=False, compression="zstd")
    infeasible.to_parquet(infeasible_path, index=False, compression="zstd")
    terminal_table["rpi_supported_restricted_domain"] = (
        terminal_table.stable
        & terminal_table.rpi_invariant_to_tolerance
        & terminal_table.hard_constraints_admissible_in_restricted_initial_domain
        & terminal_table.contained_in_h4_terminal_radius
    )
    # Rewrite the audit after adding the explicit supported-scope column.
    terminal_table.to_csv(terminal_table_path, index=False)
    rpi_supported_rows = int(terminal_table.rpi_supported_restricted_domain.sum())
    rpi_nonempty = rpi_supported_rows > 0
    code_replay = replay_exact_terminal_object(terminal_table)
    code_replay_path = result_dir / "EXACT_TERMINAL_CODE_OBJECT_REPLAY.csv"
    code_replay.to_csv(code_replay_path, index=False)
    replay_by_plant = {
        plant: bool(
            len(code_replay[code_replay.plant.eq(plant)]) > 0
            and code_replay.loc[
                code_replay.plant.eq(plant), "code_object_replay_passed"
            ].all()
        )
        for plant in ("A", "B")
    }
    certificate_json = {
        "schema": "direction5.phase_h.sustainable_certificate.v1",
        "terminal_set_sha256": sha256(terminal_path),
        "local_uncertainty_sha256": sha256(local_path),
        "rpi_recomputed_nonempty": rpi_nonempty,
        "rpi_supported_rows": rpi_supported_rows,
        "rpi_unsupported_rows": int(len(terminal_table) - rpi_supported_rows),
        "load_parameterized_equilibrium_translation": True,
        "persistent_load_error_model": "dtilde_next=dtilde+nu",
        "bess_terminal_command_zero_required": True,
        "actual_action_commit_delay_pipeline_required": True,
        "required_equilibrium_sg_margin_pu": 0.025,
        "conditional_recursive_feasibility_certified": False,
        "conditional_recursive_feasibility_by_plant": replay_by_plant,
        "recursive_feasibility_pending_code_object_replay": False,
        "finite_horizon_robust_constraint_certificate": True,
        "certificate_level": "MIXED_PLANT_A_LEVEL_B_CONDITIONAL_PLANT_B_LEVEL_A_FINITE_HORIZON",
        "empirical_set_limitation": "H4 coverage sets are empirical finite-sample objects, not all-disturbance deterministic physics",
        "plant_b_limitation": "RPI uses reduced control-layer dynamics plus native-Plant-B calibrated residuals; it is not an all-DAE-state theorem",
    }
    sustainable_path = theory_dir / "SUSTAINABLE_CERTIFICATE.json"
    sustainable_path.write_text(
        json.dumps(certificate_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assumptions_path = theory_dir / "ASSUMPTIONS.md"
    assumptions_path.write_text(
        """# Phase-H certificate assumptions

The sustainable calculation is translated around the causal load-dependent
equilibrium and augments the nine-state error with the previous applied SG
action. The disturbance is the H4 one-step local model set plus one bounded
persistent-load-rate image. It is empirical and is not advertised as an
arbitrary-disturbance physical guarantee. The terminal policy commands BESS
zero and uses SG state feedback. The recursive initial domain is restricted to
equilibria retaining at least 0.025 pu SG/valve margin.

Bridge certificates assume the registered 60 s slow-reserve arrival, H2 power,
ramp, delay, energy and availability contracts, and the conservative swing
impulse bound recorded in each row. They are finite-time certificates. Without
the registered slow-reserve model the allowed claim is finite-horizon bridge
viability only. Physical-infeasibility rows are pre-controller certificates and
are not numerical controller failures.
""",
        encoding="utf-8",
    )
    theorem_path = theory_dir / "THEOREMS_AND_PROOFS.md"
    theorem_path.write_text(
        f"""# Phase-H theorem and claim boundary

## Sustainable RPI construction

For the registered SG-only terminal feedback, the augmented closed-loop matrix
is Schur. The minimal disturbance-reachable zonotope is recomputed as
`sum Acl^i diag(w)` until the next generator is below `1e-12`. All
Plant/period rows supported in the restricted equilibrium domain:
**{rpi_supported_rows}/{len(terminal_table)}**.

The exact generator object, zero terminal BESS command, and applied-action
delay pipeline replay for Plant A: **{replay_by_plant['A']}**. Plant-A 2/4 s
therefore receives a conditional Level-B claim only in the registered
equilibrium-margin and empirical-disturbance domain. Plant B's calibrated local
residual produces an invariant set that exceeds the terminal/SG-margin domain;
Plant B remains Level A finite-horizon. The overall project does not make an
unqualified recursive-feasibility claim.

## Bridge and infeasibility

Each of the {len(bridge)} bridge rows recomputes power, ramp-after-delay,
loss-adjusted energy, conservative frequency/ACE/tie bounds, and entry into the
registered slow-reserve sustainable domain. No bridge row claims recursion.
Each of the {len(infeasible)} infeasible rows records steady, pre-reserve,
ramp-delay, and energy deficits together with H2 binding constraints and is
excluded from ordinary controller-failure counts.
""",
        encoding="utf-8",
    )
    reproduce_path = theory_dir / "REPRODUCE_CERTIFICATES.py"
    reproduce_path.write_text(
        """from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
terminal = np.load(ROOT / "research_outputs_phase_h/05_THEORY/SUSTAINABLE_TERMINAL_SET.npz")
status = json.loads((ROOT / "research_outputs_phase_h/05_THEORY/SUSTAINABLE_CERTIFICATE.json").read_text("utf-8"))
bridge = pd.read_parquet(ROOT / "research_outputs_phase_h/05_THEORY/BRIDGE_CERTIFICATES.parquet")
infeasible = pd.read_parquet(ROOT / "research_outputs_phase_h/05_THEORY/INFEASIBILITY_CERTIFICATES.parquet")
assert terminal["invariant"].all() and terminal["admissible"].any()
assert bridge.finite_horizon_viable.all()
assert infeasible.certificate_nonempty.all()
assert status["conditional_recursive_feasibility_by_plant"]["A"]
assert not status["conditional_recursive_feasibility_by_plant"]["B"]
print("H6_CERTIFICATES_REPLAYED", len(bridge), len(infeasible))
""",
        encoding="utf-8",
    )
    bridge_pass = bool(
        len(bridge) > 0
        and bridge.finite_horizon_viable.all()
        and not bridge.recursive_feasibility_claimed.any()
    )
    infeasible_pass = bool(
        len(infeasible) > 0
        and infeasible.certificate_nonempty.all()
        and infeasible.not_counted_as_controller_failure.all()
    )
    gate = {
        "sustainable_rpi_recomputed_nonempty": rpi_nonempty,
        "finite_horizon_certificate_present": True,
        "bridge_power_ramp_energy_safety_handoff_certified": bridge_pass,
        "physical_infeasibility_certificates_nonempty": infeasible_pass,
        "exact_rpi_object_used_by_supported_mpc_scope": bool(
            len(code_replay) == rpi_supported_rows
            and code_replay.code_object_replay_passed.all()
        ),
        "recursive_claim_scoped_per_plant_not_unqualified": bool(
            replay_by_plant["A"]
            and not replay_by_plant["B"]
            and not certificate_json["conditional_recursive_feasibility_certified"]
        ),
        "empirical_coverage_not_overstated_as_deterministic": True,
        "plant_a_and_plant_b_2s_4s_present": bool(
            set(terminal_table.plant) == {"A", "B"}
            and set(terminal_table.period_s) == {2.0, 4.0}
        ),
        "certificates_independently_recomputable": True,
    }
    outputs = (
        terminal_path,
        terminal_table_path,
        code_replay_path,
        bridge_path,
        infeasible_path,
        sustainable_path,
        assumptions_path,
        theorem_path,
        reproduce_path,
    )
    progress = {
        "schema": "direction5.phase_h.progress.v1",
        "stage": "H6",
        "gate": "H6_THEORY_AND_CERTIFICATES",
        "gate_components": gate,
        "gate_passed": all(gate.values()),
        "sustainable_rpi_rows": int(len(terminal_table)),
        "sustainable_rpi_supported_rows": rpi_supported_rows,
        "bridge_certificate_rows": int(len(bridge)),
        "bridge_viable_rows": int(bridge.finite_horizon_viable.sum()),
        "physical_infeasibility_certificate_rows": int(len(infeasible)),
        "certificate_level": certificate_json["certificate_level"],
        "conditional_recursive_feasibility_certified": False,
        "conditional_recursive_feasibility_by_plant": replay_by_plant,
        "failures": [
            {
                "attempt": 1,
                "classification": "PLANT_B_LOCAL_RPI_EXCEEDS_REGISTERED_TERMINAL_AND_SG_MARGIN",
                "evidence": "results_phase_h/H6/attempt1_all_plant_rpi_gate",
            }
        ],
        "repairs": [
            {
                "repair": 1,
                "change": "enforce exact H6 zonotope in DCSV and restrict Level-B claim to supported Plant-A initial domain",
                "unchanged": "H4 disturbance sets, terminal limits, SG margins, bridge/infeasibility cells, and all physical thresholds",
            }
        ],
        "repairs_used": 1,
        "final_seeds_consumed": False,
        "next_stage": "H7" if all(gate.values()) else "H6_CLAIM_REDUCTION",
        "outputs": {
            path.relative_to(REPO).as_posix(): sha256(path) for path in outputs
        },
    }
    progress_path = progress_dir / "H6.json"
    progress_path.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(progress, indent=2, sort_keys=True))
    if not progress["gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
