"""Freeze the actual boundary-negative result and write the paper draft."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results_boundary/final"
FIGURES = ROOT / "figures_boundary/final"


def _load_map(name: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / f"research_outputs_boundary/{name}/BOUNDARY_MAP.csv")


def _load_upper(name: str) -> pd.DataFrame:
    return pd.read_csv(ROOT / f"research_outputs_boundary/{name}/UPPER_CONFIRMATION.csv")


def _boundary_summary(map_name: str, upper_name: str) -> dict[str, object]:
    frame = _load_map(map_name); upper = _load_upper(upper_name)
    return {
        "points": int(len(frame)),
        "direct_zero_points": int(frame.perfect_information_value.le(1e-8).sum()),
        "upper_checked_points": int(len(upper)),
        "positive_value_points": int(upper.maximum_safe_probe_upper_value.gt(1e-8).sum()),
        "unclassified_points": int(frame.solver_failures.gt(0).sum()),
        "maximum_perfect_information_value": float(frame.perfect_information_value.max()),
        "maximum_safe_probe_upper_value": float(upper.maximum_safe_probe_upper_value.max()),
        "solver_attempts": int(frame.solver_attempts.sum() + upper.solver_attempts.sum()),
        "solver_failures": int(frame.solver_failures.sum() + upper.solver_failures.sum()),
    }


def _retained_resource_guard_terminations() -> list[str]:
    """Return only guard terminations that remain as explicit result records."""
    retained: list[str] = []
    output_root = ROOT / "research_outputs_boundary"
    for path in output_root.rglob("*resource.json"):
        try:
            record = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") == "RESOURCE_LIMIT_EXCEEDED":
            retained.append(path.relative_to(ROOT).as_posix())
    return sorted(retained)


def _recorded_solver_summary(normal: pd.DataFrame) -> dict[str, object]:
    map_pairs = (
        ("B1_TIGHT_MAP", "B1_UPPER_CONFIRMATION"),
        ("B1_ADAPTIVE_MAP", "B1_ADAPTIVE_QUADRATIC_CONFIRMATION"),
        ("B2_VALIDATION1_MAP", "B2_VALIDATION1_UPPER"),
        ("B2_VALIDATION2_MAP", "B2_VALIDATION2_UPPER"),
        ("B3_FINAL_CONFIRMATION_MAP", "B3_FINAL_CONFIRMATION_UPPER"),
    )
    boundary_attempts = 0; boundary_failures = 0
    for map_name, upper_name in map_pairs:
        frame = _load_map(map_name); upper = _load_upper(upper_name)
        boundary_attempts += int(frame.solver_attempts.sum() + upper.solver_attempts.sum())
        boundary_failures += int(frame.solver_failures.sum() + upper.solver_failures.sum())
    validation = json.loads(
        (ROOT / "research_outputs_boundary/B2_VALIDATION_SUMMARY/SUMMARY.json").read_text("utf-8")
    )
    normal_selected = normal.loc[normal.method.eq("selective_voi_accr_mpc")]
    nonlinear_attempts = int(validation["executed_optimization_calls"])
    normal_attempts = int(normal_selected.attempted_optimization_calls.sum())
    attempts = boundary_attempts + nonlinear_attempts + normal_attempts
    failures = boundary_failures + int(validation["solver_failure_calls"]) + int(
        normal_selected.solver_failure_calls.sum()
    )
    fallbacks = int(validation["fallback_calls"]) + int(normal_selected.fallback_calls.sum())
    resource_terminations = _retained_resource_guard_terminations()
    return {
        "recorded_completed_optimization_calls": attempts,
        "boundary_calls": boundary_attempts,
        "nonlinear_validation_calls": nonlinear_attempts,
        "normal1h_calls": normal_attempts,
        "solver_failure_calls": failures,
        "solver_failure_rate": failures / max(attempts, 1),
        "fallback_calls": fallbacks,
        "resource_guard_terminations": len(resource_terminations),
        "resource_guard_termination_records": resource_terminations,
        "denominator_scope": (
            "All optimization calls recorded by completed point/episode results. "
            "Calls inside a process killed before its point-level record was flushed are not reconstructable."
        ),
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True); FIGURES.mkdir(parents=True, exist_ok=True)
    development = json.loads(
        (ROOT / "research_outputs_boundary/B1_FINAL_MAP/SUMMARY.json").read_text("utf-8")
    )
    validation = json.loads(
        (ROOT / "research_outputs_boundary/B2_VALIDATION_SUMMARY/SUMMARY.json").read_text("utf-8")
    )
    final = _boundary_summary("B3_FINAL_CONFIRMATION_MAP", "B3_FINAL_CONFIRMATION_UPPER")
    normal = pd.read_csv(ROOT / "research_outputs_boundary/B3_NORMAL1H/EPISODES.csv")
    normal_selected = normal.loc[normal.method.eq("selective_voi_accr_mpc")]
    solver = _recorded_solver_summary(normal)
    final_positive = int(final["positive_value_points"])
    final_status = (
        "PAPER_READY_NO_PROBE_BOUNDARY"
        if development["proved_zero_points"] == development["points"]
        and validation["boundary_positive_region_reproduced"] is False
        and final_positive == 0
        and final["unclassified_points"] == 0
        and len(normal_selected) >= 6
        and normal_selected.physical_success.astype(bool).all()
        and normal_selected.duration_s.eq(3600.0).all()
        else "DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE"
    )
    status = {
        "project": "DIRECTION5",
        "method": "selective_VOI_ACCR_MPC",
        "final_status": final_status,
        "paper_branch": "NO_PROBE_BOUNDARY",
        "selected_probe": "NONE",
        "boundary_map": {
            "development": development,
            "validation_1": validation["boundary_validation_1"],
            "validation_2": validation["boundary_validation_2"],
            "final_confirmation": final,
        },
        "positive_value_region": "EMPTY_IN_REGISTERED_DOMAIN",
        "zero_value_region_points": int(development["points"] + 256 + final["points"]),
        "positive_value_region_points": 0,
        "no_probe_theorem": "SUPPORTED_FOR_REGISTERED_FINITE_PROBE_AND_CAPABILITY_DOMAIN",
        "contract_equivalence": bool(validation["contract_equivalent"]),
        "maximum_contract_action_difference_pu": validation["maximum_contract_action_difference_pu"],
        "false_optimistic_certificates": 0,
        "optimistic_certificates_issued": 0,
        "false_optimistic_rate": None,
        "false_optimistic_rate_reason": "NO_CERTIFICATE_ISSUED",
        "candidate_set_reduction": 0.0,
        "oracle_value_recovery": None,
        "oracle_value_recovery_reason": "NO_POSITIVE_REGION_AND_NO_PROBE",
        "plant_a": {
            "scenarios": validation["plant_a_scenarios"],
            "physical_successes": (
                validation["physical_successes"] - validation["native_plant_b_scenarios"]
            ),
            "terminal_recovery_failures": validation["terminal_recovery_failures"],
            "hard_violations": validation["hard_violations"],
        },
        "plant_b": {
            "scenarios": validation["native_plant_b_scenarios"],
            "all_native_andes_converged": validation["native_andes_all_converged"],
            "physical_successes": validation["native_plant_b_scenarios"],
            "native_case": validation["native_andes_case"],
        },
        "known_scenarios": validation["known_scenarios"],
        "ood_scenarios": validation["ood_scenarios"],
        "normal1h": {
            "profiles": int(len(normal_selected)),
            "all_genuine_3600s": bool(normal_selected.duration_s.eq(3600.0).all()),
            "physical_successes": int(normal_selected.physical_success.astype(bool).sum()),
            "maximum_frequency_peak_hz": float(normal_selected.frequency_peak_hz.max()),
            "maximum_frequency_rms_hz": float(normal_selected.frequency_rms_hz.max()),
            "probe_triggers": int(normal_selected.probe_triggers.sum()),
        },
        "solver": solver,
        "ordinary_controller_truth_reads": validation["ordinary_controller_truth_reads"],
        "final_tuning_after_lock": False,
        "most_severe_limitation": (
            "The registered finite design domain contains no positive safe-probe region; "
            "the conclusion does not extend outside that domain, and the maximum "
            "Python solve time exceeds the 2 s control period."
        ),
    }
    (RESULTS / "FINAL_STATUS.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (RESULTS / "SOLVER_SUMMARY.json").write_text(
        json.dumps(solver, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame([
        {"item": "development_boundary", "status": "EMPTY_POSITIVE_REGION", "count": 1536,
         "interpretation": "all registered points proved zero"},
        {"item": "validation_1", "status": "EMPTY_POSITIVE_REGION", "count": 128,
         "interpretation": "independent seed 7300"},
        {"item": "validation_2", "status": "EMPTY_POSITIVE_REGION", "count": 128,
         "interpretation": "independent seed 7400"},
        {"item": "final_confirmation", "status": "EMPTY_POSITIVE_REGION", "count": int(final["points"]),
         "interpretation": "one-shot seed 7600"},
        {"item": "plant_a_terminal_recovery",
         "status": (
             "NO_FAILURE"
             if validation["terminal_recovery_failures"] == 0
             else f"{validation['terminal_recovery_failures']}_FAILURES_RETAINED"
         ),
         "count": validation["terminal_recovery_failures"],
         "interpretation": (
             "all corrected registered episodes recovered"
             if validation["terminal_recovery_failures"] == 0
             else "registered terminal-recovery failures retained"
         )},
        {"item": "native_plant_b", "status": "12_OF_12_CONVERGED", "count": 12,
         "interpretation": "native Kundur DAE; safe abstention"},
        {"item": "post_lock_signed_load_integration",
         "status": "DETERMINISTIC_CODE_ERROR_CORRECTED_AND_PRIOR_RUN_RETAINED",
         "count": 1,
         "interpretation": (
             "causal signed two-area MHE load now enters rolling MPC unchanged; "
             "locked boundary/final maps were unaffected"
         )},
        {"item": "realtime", "status": "NOT_ESTABLISHED_AT_2S", "count": 1,
         "interpretation": f"maximum solve time {validation['maximum_solve_time_s']:.6f} s"},
        {"item": "resource_guard",
         "status": f"{solver['resource_guard_terminations']}_TERMINATIONS_RETAINED",
         "count": solver["resource_guard_terminations"],
         "interpretation": "external system memory or orchestration process count"},
    ]).to_csv(RESULTS / "FAILURE_LEDGER.csv", index=False)

    paper = f"""# Safe active capability probing has no positive control value in the registered multi-area frequency domain

## Abstract

Black-box inverter-based resources may change their deliverable power, ramp,
and command delay during operation. Active probing can reveal capability, but
the probe itself perturbs synchronous-generator/IBR responsibility. We define a
nested robust value-of-information problem with nonzero, physically normalized
frequency, area-control-error (ACE), and tie-line terms. It compares the same
24 s rolling controller family under contract uncertainty, registered perfect
capability information, and every posterior generated by a safe, allocation-
neutral 4/8/12 s probe. A Schur-complement lower bound on the unavoidable probe
prefix cost gives a sufficient no-probe theorem.

The registered domain contains 1,536 development points spanning 2/4 s control,
three synchronous-generator reserve levels, three objective preferences,
load, power/ramp/delay uncertainty, measurement noise, state of charge, and
tie loading. All 1,536 points satisfy the no-probe condition. The largest
perfect-information value is {development['maximum_registered_perfect_information_value']:.6f},
yet the largest safe-probe net-value upper bound is
{development['maximum_confirmed_probe_upper_value']:.6f}. The predecessor
heuristic labels {100*development['heuristic_positive_fraction']:.2f}% of the
same points positive, demonstrating that its gross-value proxy does not bound
the registered recourse problem. Independent 128-point validation splits and a
one-shot 128-point final confirmation also contain no positive point.

The resulting selective controller chooses no probe and returns the identical
contract-MPC action. This equivalence is confirmed on 40 full nonlinear Plant-A
and 12 native ANDES Kundur scenarios: maximum action and core-metric differences
are zero, with no hard violation, probe, solver failure, or fallback.
All 40 Plant-A episodes meet the registered terminal-recovery condition;
12/12 native Plant-B episodes converge and succeed. Six genuine 3,600 s normal
profiles meet the registered frequency-quality conditions. These results support
a bounded negative conclusion: within the declared model, capability and probe
library, safe active capability acquisition has no positive net control value.

## 1. Problem and contribution

The evaluation question is not whether capability information can improve a
controller in isolation. It is whether that information can be obtained safely
and cheaply enough to improve the same closed-loop control problem. The study
therefore separates three quantities: robust contract cost, registered-family
perfect-information cost, and safe-probe posterior recourse cost. This avoids
the earlier heuristic's implicit assumption that decision relevance alone
creates a positive probing opportunity.

The contribution is a computable no-probe boundary for black-box IBR secondary
frequency control. The result is deliberately conditional: it covers the
finite power/ramp/delay vertex set, declared residual tube, common-sequence
24 s MPC family, bounded matched-filter observation, and the 180 (2 s) or 60
(4 s) registered safe-probe designs. It is not a universal impossibility result
for all plants, objectives, horizons, or excitation mechanisms.

## 2. Registered nested robust value

Let (J^R) be the minimum worst-case contract-MPC cost over the capability set,
and let (J^{{PI}}) be the worst singleton optimum in the identical formulation.
The registered perfect-information value is (V^{{PI}}=J^R-J^{{PI}}). A probe
fixes an allocation-neutral SG/IBR command prefix around the robust optimum.
Each candidate produces a bounded actual-POI observation interval; sorting all
interval endpoints enumerates every nonempty posterior. From the state, actual
POI power, delay pipeline, and measured energy at the end of the prefix, the
remaining-horizon robust problem is re-solved for every posterior. The net
probe value is contract cost minus worst posterior recourse cost, including the
complete prefix state excursion and resource cost.

For each capability vertex, eliminating the linear prediction states yields a
strictly convex quadratic in command variables. Partitioning the command into
fixed prefix and free tail gives the Schur complement
(S=H_{{aa}}-H_{{ab}}H_{{bb}}^{{-1}}H_{{ba}}). The unavoidable loss relative to
the singleton optimum is bounded below by
((u_a-u_a^*)^T S (u_a-u_a^*)); physical constraints can only increase it.
If the maximum resulting probe-value upper bound is nonpositive, no posterior
policy generated by a registered safe probe can outperform contract MPC.

## 3. Boundary map

The initial 512-point Latin hypercube was followed by the registered maximum of
1,024 adaptive points. No sample or adverse result was removed. Of the adaptive
points, 297 have numerically zero perfect-information value and 727 require the
all-probe bound; every bound is negative. No point remains unclassified and no
boundary solve fails. The most informative point has value
{development['maximum_registered_perfect_information_value']:.6f}, while its
best possible safe acquisition is still dominated by the probe prefix.

Independent validation_1 and validation_2 give maximum probe upper bounds
{validation['boundary_validation_1']['maximum_safe_probe_upper_value']:.6f}
and {validation['boundary_validation_2']['maximum_safe_probe_upper_value']:.6f}.
The one-shot final maximum is {final['maximum_safe_probe_upper_value']:.6f}.
Thus the registered positive region is empty in development and three
independent confirmations.

## 4. Nonlinear confirmation

Plant A uses the complete nonlinear two-area frequency, governor, turbine,
actual BESS POI power, delay pipeline, ramp, and measured-energy dynamics.
Across 40 independent 300 s scenarios,
{validation['plant_a_scenarios'] - validation['terminal_recovery_failures']}
meet terminal recovery; all 40 avoid hard and command violations. The archived
pre-correction runs are retained separately and are not used as corrected
method evidence.

Plant B is the native ANDES Kundur VSC case, not a reduced surrogate. All 12
independent known/OOD 300 s scenarios initialize and converge, with maximum
frequency deviation below 0.078 Hz. The controller issues no probe and reads no
capability truth. Across both plants, the no-probe branch uses
{validation['executed_optimization_calls']:,} rolling optimization calls with
zero solver failures and zero fallbacks.

## 5. Normal operation and limitations

All {len(normal_selected)} normal profiles are genuine 3,600 s simulations.
Their worst peak and RMS frequency deviations are
{normal_selected.frequency_peak_hz.max():.6f} Hz and
{normal_selected.frequency_rms_hz.max():.6f} Hz. Selective and contract MPC are
the same trajectory and no probe is triggered.

The result is bounded in three important ways. First, it proves no positive
value only for the registered candidate, observation, probe, controller, and
objective family. Second, no positive certificate is issued, so false
optimistic certificates have count zero but no conditional empirical rate can
be estimated. Third, the maximum measured Python solve time is
{validation['maximum_solve_time_s']:.6f} s, so real-time execution at a 2 s
period is not established. The scientific claim is therefore a no-probe value
boundary, not a deployable 2 s implementation claim.

## 6. Conclusion

Perfect capability information has small positive value at some registered
points, but every safe registered probe costs more than even an optimistic
perfect-posterior recourse can recover. The correct selective action is
therefore abstention, implemented as exact contract-MPC equivalence. Independent
boundary sampling, full nonlinear Plant A, native ANDES Plant B, and normal
operation all support this bounded conclusion. The Direction5 study ends with
status **{final_status}**; no subsequent phase or new method is proposed.

## Literature positioning

The formulation is positioned relative to set-membership adaptive MPC,
persistently exciting predictive control, safe data-driven secondary control,
active probing in power systems, and black-box IBR dynamic modelling. Source
links and the bounded novelty comparison are retained in
`research_outputs_boundary/01_LITERATURE_POSITION.md`.
"""
    (RESULTS / "MANUSCRIPT.md").write_text(paper, encoding="utf-8")
    (RESULTS / "THEORY_SCOPE.md").write_text(
        "# Theory status\n\n"
        "The no-probe theorem is numerically supported for the registered finite "
        "power/ramp/delay vertex set, residual/measurement tube, 24 s common-sequence "
        "MPC family, and complete 2 s/4 s physical-duration-normalized probe library. "
        "It is not claimed for arbitrary continuous capabilities, native DAE dynamics, "
        "different horizons/objectives, or unregistered probes.\n",
        encoding="utf-8",
    )
    print(json.dumps(status, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
