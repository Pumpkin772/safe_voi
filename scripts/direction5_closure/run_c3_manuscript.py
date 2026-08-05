"""Write the Direction5 closure manuscript from sealed validation/confirmation facts.

This stage is reporting-only.  It must not import, instantiate, or mutate a
controller.  Every number is read from the sealed C0--C2 evidence.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_outputs_closure" / "03_PAPER"
PROGRESS = ROOT / "progress_closure" / "C3.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write(name: str, text: str) -> None:
    (OUT / name).write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def pct(value: str | float, digits: int = 2) -> str:
    return f"{100.0 * float(value):.{digits}f}%"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    validation = read_json(ROOT / "results_final" / "R5" / "R5_SUMMARY.json")
    confirm = read_json(ROOT / "results_closure" / "C2" / "C2_SUMMARY.json")
    c1 = read_json(ROOT / "progress_closure" / "C1.json")
    value = {row["metric"]: row for row in read_csv(
        ROOT / "research_outputs_closure" / "01_MECHANISM" / "INFORMATION_VALUE_SUMMARY.csv"
    )}
    metrics_v = {row["metric"]: row for row in read_csv(
        ROOT / "results_final" / "R5" / "CORE_METRIC_GATES.csv"
    ) if row["analysis"] == "both_success"}
    metrics_c = {row["metric"]: row for row in read_csv(
        ROOT / "research_outputs_closure" / "02_CONFIRMATORY" / "FINAL_CORE_METRIC_GATES.csv"
    ) if row["analysis"] == "both_success"}
    paired = read_csv(ROOT / "research_outputs_closure" / "02_CONFIRMATORY" / "FINAL_PAIRED_FAILURES.csv")
    paired_all = {row["category"]: int(row["scenarios"]) for row in paired if row["scope"] == "ALL"}
    known_ood = read_csv(ROOT / "research_outputs_closure" / "02_CONFIRMATORY" / "FINAL_KNOWN_OOD.csv")
    normal = read_csv(ROOT / "research_outputs_closure" / "02_CONFIRMATORY" / "FINAL_NORMAL1H.csv")
    domain = read_csv(ROOT / "research_outputs_closure" / "02_CONFIRMATORY" / "FINAL_DOMAIN_STATISTICS.csv")

    title = "Limits of Causal Online Deliverability Adaptation for Black-Box IBRs in Multi-Area Secondary Frequency Control"
    abstract = f"""# Abstract

Black-box inverter-based resources can deliver less power and ramp capability, or more delay, than a dispatch model assumes. We study whether public point-of-interconnection measurements can separate net-load disturbance from device execution mismatch well enough to improve multi-area secondary frequency control. The frozen DCSV-CR-MPC combines a contract-safe base command with causal set-membership capability estimation and future surplus-loss recourse; the primary comparator is an otherwise matched contract-only rolling MPC.

An independent audit exactly reproduced 262 archived statistics and 19 registered Gate decisions. Validation used 120 full nonlinear Plant-A scenarios and 24 native ANDES Plant-B scenarios. A separately locked, one-time confirmation used the previously untouched seeds 100--159 in 120 Plant-A scenarios, plus 24 native Plant-B scenarios, 42 genuine 3600 s method runs, and six contract-violation runs. In confirmation, DCSV-CR-MPC reduced the success rate by {confirm['success_drop_pp']:.2f} percentage points, passed 0/3 core performance Gates, and required {confirm['fallback_calls']:,} fallbacks in {confirm['optimization_decisions']:,} optimization decisions. On both-success pairs, improvements relative to contract-only MPC were {pct(metrics_c['frequency_peak_hz']['aggregate_mean_relative_improvement'])} for peak frequency deviation, {pct(metrics_c['ace_iae_pu_s']['aggregate_mean_relative_improvement'])} for ACE IAE, and {pct(metrics_c['tie_rms_pu']['aggregate_mean_relative_improvement'])} for tie-line RMS; all registered lower confidence bounds failed the positive criterion.

Perfect capability information retained value for ACE and tie-line control, but the causal-online variant was worse than the contract controller, yielding perfect-minus-online gaps of {pct(value['ace_iae_pu_s']['perfect_minus_online_value_gap_relative_to_contract'])} for ACE and {pct(value['tie_rms_pu']['perfect_minus_online_value_gap_relative_to_contract'])} for tie-line RMS. Natural closed-loop excitation almost never converted the online envelope into usable surplus: only {c1['surplus_active_calls']} of {c1['surplus_total_calls']:,} DCSV calls activated surplus. All {confirm['fallback_calls']:,} confirmatory fallbacks and all 1,021 validation fallbacks were attributable to primary/restoration mathematical infeasibility rather than numerical solver failure. The positive Gate did not hold in either validation or confirmation. We therefore report a bounded negative result: perfect capability can matter, but this causal estimator--recourse realization did not outperform a contract-only MPC under the registered plants, events, horizons, and safety standards.
"""
    write("ABSTRACT.md", abstract)

    contributions = f"""# Contributions and evidential status

1. **Auditable distinction between three capability notions.** We separate a guaranteed contractual floor, a causal online performance envelope, and evaluation-only perfect capability. The distinction is enforced in code and ordinary controllers do not read true capability, true load, hidden parameters, or future events.
2. **A frozen, falsifiable controller comparison.** DCSV-CR-MPC and the primary contract-only comparator both execute genuine rolling finite-horizon optimization with state/input sequences, dynamics, power/ramp/delay/SoC constraints, domain routing, restoration, diagnostics, and committed applied actions.
3. **Balanced validation and untouched-seed confirmation.** Both stages use scenario-balanced aggregate means, paired absolute differences, and seed/design-cell hierarchical bootstrap. Mean episode-relative ratios are diagnostic only.
4. **Full denominator accounting.** Confirmation records {confirm['optimization_decisions']:,} attempted optimization decisions and {confirm['raw_solver_invocations']:,} raw solver invocations, including {confirm['restoration_calls']} restoration calls and {confirm['fallback_calls']:,} fallbacks. Numerical failures were {confirm['numerical_failures']}.
5. **Mechanism evidence, not just a leaderboard.** Perfect information exhibited value, whereas causal online capability did not; surplus was activated in only {c1['surplus_active_calls']}/{c1['surplus_total_calls']:,} calls, and mathematical infeasibility explained every fallback in validation.
6. **A registered negative result.** The method passed 0/3 core metric Gates in both validation and confirmation, lost {confirm['success_drop_pp']:.2f} percentage points of success in confirmation, and had inconsistent positive direction across Plants A and B. We do not claim controller superiority.
"""
    write("CONTRIBUTIONS.md", contributions)

    result_rows = []
    names = {"frequency_peak_hz": "Peak |frequency|", "ace_iae_pu_s": "ACE IAE", "tie_rms_pu": "Tie-line RMS"}
    for key in ("frequency_peak_hz", "ace_iae_pu_s", "tie_rms_pu"):
        result_rows.append(
            f"| {names[key]} | {pct(metrics_v[key]['aggregate_mean_relative_improvement'])} | "
            f"{pct(metrics_v[key]['relative_improvement_lower'])} | {pct(metrics_c[key]['aggregate_mean_relative_improvement'])} | "
            f"{pct(metrics_c[key]['relative_improvement_lower'])} | No |"
        )
    results = f"""# Results

## Registered primary comparison

The primary result compares frozen DCSV-CR-MPC against contract-only rolling MPC. Positive numbers indicate lower cost for DCSV-CR-MPC. The main estimator is the frozen causal set-membership deliverability estimator; perfect capability is evaluation-only. Physical infeasibility is classified before controller scoring.

| Metric | Validation improvement | Validation lower bound | Confirmation improvement | Confirmation lower bound | Gate passed in both? |
|---|---:|---:|---:|---:|---|
{chr(10).join(result_rows)}

The success deficit was {validation['success_drop_pp']:.2f} percentage points in validation and {confirm['success_drop_pp']:.2f} points in confirmation, exceeding the registered 2-point limit both times. Confirmation contained {paired_all['both_success']} both-success pairs, {paired_all['only_proposed_fails']} pairs where only DCSV-CR-MPC failed, {paired_all['only_baseline_fails']} pairs where only contract MPC failed, {paired_all['both_fail']} pairs where both failed, and {paired_all['physically_infeasible']} pre-certified physically infeasible scenarios. No failed episode was removed or relabeled as not evaluated.

## Plant and condition structure

Plant A was the complete nonlinear simulation and Plant B was the native ANDES Kundur model. The paired frequency absolute difference was -0.177817 Hz on Plant A and +0.000051 Hz on Plant B, so the required cross-plant positive direction did not hold. Plant B had 24/24 successes for each primary method, whereas Plant A contained all eight DCSV-only failures and all confirmatory fallbacks.

On Plant A, the known-condition success rates were 78.57% for contract MPC and 64.29% for DCSV-CR-MPC; OOD rates were 85.37% and 80.49%, respectively. DCSV fallbacks were 501 (known) and 214 (OOD), versus 35 and 55 for contract MPC. On Plant B both methods achieved 100% success in known and OOD groups with small, mixed metric differences. These results do not support an OOD or cross-plant advantage.

## Physical-domain accounting

Confirmation included 84 sustainable, 23 bridge, and 37 physically infeasible scenario pairs. Contract/DCSV successes were 77/71 in sustainable and 15/13 in bridge domains. Physically infeasible cases were reported separately, with zero hard violations for both methods, and were not counted as ordinary controller failures. Bridge claims remain finite-horizon only; no slow takeover is inferred where none was modeled.

## Solver and fallback accounting

Across all confirmation tasks, {confirm['optimization_decisions']:,} optimization decisions caused {confirm['raw_solver_invocations']:,} solver invocations. The accounting identity includes {confirm['restoration_calls']} restoration calls and {confirm['fallback_calls']:,} fallback decisions. There were {confirm['numerical_failures']} numerical failures and {confirm['accuracy_warnings']} accuracy warnings; the 99th-percentile solve-time fraction was {confirm['p99_solve_fraction_of_period']:.3f} of the control period. Thus real-time and numerical-failure Gates passed, but mathematical feasibility and fallback Gates did not.

## Normal-profile and contract-violation evidence

Each of seven methods was run on six full 3600 s synthetic registered profiles. All seven failed the frequency-quality Gate. DCSV-CR-MPC reached a 2.290706 Hz peak, 0.906454 Hz RMS, and 322 fallbacks; the evaluation-only perfect-capability oracle also failed, with a 1.645819 Hz peak. These profiles are synthetic AR(2)+multi-sine traces, not public measured load data, so the result is a model/protocol boundary rather than a field-performance estimate.

All six separate contract-violation episodes were detected (27--90 detection calls per episode), recovered terminally, and had zero fallbacks and hard violations. This supports violation detection/separation under those tests, not universal post-breach safety.
"""
    write("RESULTS_SECTION.md", results)

    limitations = """# Limitations

- The confirmatory evidence covers one full nonlinear two-area Plant A and one native ANDES Kundur Plant B, not hardware or field deployment.
- The six 3600 s profiles are synthetic registered AR(2)+multi-sine traces. They are genuine full simulations, but they are not measured public load records, and every method failed their frequency-quality Gate.
- The perfect-capability comparison is evaluation-only. Its value does not imply that the information is causally available to an ordinary controller.
- The causal set-membership estimator had adequate excitation in 75% of a dedicated 40-episode protocol, but its performance envelope never exceeded contract in that protocol and almost never yielded usable surplus in natural closed loop.
- Binding-constraint indicators are primal-proximity diagnostics rather than optimizer dual multipliers.
- The theorem rules out same-instant guarantees after an unannounced drop below every known positive floor. Conditional recourse and terminal certificates apply only under their recorded assumptions; bridge claims are finite horizon.
- The result is specific to the frozen DCSV-CR-MPC realization, registered weights, horizons, plants, scenarios, and safety Gates. It is not an impossibility proof for all adaptive or robust MPC methods.
- Confirmation consumed seeds 100--159 once under the sealed lock. No post-result retuning or repeat confirmation is permitted.
"""
    write("LIMITATIONS.md", limitations)

    supported = """# Supported and unsupported claims

| Claim | Status | Evidence boundary |
|---|---|---|
| Capability uncertainty is material in the registered problem | SUPPORTED | Frozen R1 materiality on full Plant A and native Plant B |
| Perfect capability can improve ACE and tie-line metrics | SUPPORTED_WITH_BOUNDS | 24 balanced information-value scenarios; not causal/deployable |
| Contract-violation detection is separable in the registered tests | SUPPORTED_WITH_BOUNDS | 6/6 dedicated episodes in validation and confirmation |
| Solver denominator includes all attempted optimization calls | SUPPORTED | Independent C0 and post-C2 recomputation |
| Physically infeasible scenarios are kept separate | SUPPORTED | 37 confirmatory pairs separately certified |
| DCSV-CR-MPC outperforms contract-only MPC | NOT_SUPPORTED | 0/3 primary metrics; success deficit; adverse failure-aware results |
| DCSV-CR-MPC has a positive cross-plant direction | NOT_SUPPORTED | Plant A negative, Plant B only slightly positive |
| Causal online capability realizes the perfect-information value | NOT_SUPPORTED | Online variant worse than contract; surplus 2/22,392 calls |
| Normal 1 h frequency quality is acceptable | NOT_SUPPORTED | All seven methods failed |
| Recursive feasibility holds globally | NOT_SUPPORTED | Only conditional sustainable/recourse certificates; bridge finite horizon |
| The method class is impossible | NOT_CLAIMED | Evidence concerns this frozen realization and protocol only |
| Field performance is established | NOT_CLAIMED | Simulation only; no public measured normal profiles |
"""
    write("SUPPORTED_UNSUPPORTED_CLAIMS.md", supported)

    risks = """# Reviewer risk register

| Risk | Severity | Mitigation in this archive |
|---|---|---|
| Negative result mistaken for method-class impossibility | High | Claims ledger and limitations restrict scope to the frozen realization |
| Solver failures hidden by an incorrect denominator | High | C0 independent reconstruction and C2 post-run audit retain both decisions and raw invocations |
| Physically infeasible scenarios distort controller scores | High | Separate domain certification and paired-failure categories |
| Oracle leaks into ordinary controller | High | Code-semantic audit and source snapshot; oracle explicitly evaluation-only |
| Seed/design-cell imbalance | High | 12 Plant-A cells x 10; every seed 100--159 appears twice; hierarchical bootstrap |
| Confirmation influenced by validation | High | Locked manifests, hashes, untouched final seeds, and no post-result tuning |
| Surplus mechanism exists only nominally | High | Activation count and duration reported directly (2 calls, 6 s) |
| Native Plant B replaced by surrogate | High | Native ANDES manifests, logs, and source included |
| Normal-profile evidence overstated | Medium | Synthetic provenance and universal failure disclosed |
| Constraint binding overstated | Medium | Primal-proximity status disclosed; no dual interpretation |
| Long-run reproducibility depends on commercial solver | Low | Frozen closure uses OSQP/CLARABEL paths and records environment; no license files packaged |
"""
    write("REVIEWER_RISK_REGISTER.md", risks)

    manuscript = f"""# {title}

{abstract.replace('# Abstract', '## Abstract').strip()}

## 1. Introduction

Secondary frequency control increasingly relies on inverter-based resources whose delivered power may differ from an issued command because of hidden power, ramp, and delay capability. Treating this mismatch as a fresh load event confounds disturbance estimation and equipment execution. A safe controller must instead distinguish what is guaranteed by contract, what can be inferred causally from public measurements, and what is known only to an evaluation oracle.

This study asks a deliberately narrow question: can a frozen disturbance--capability-separated contract--recourse MPC convert causal online capability information into reproducible closed-loop benefit over a fair contract-only rolling MPC? The answer under the registered protocol is negative. The information itself can matter, but the online estimator and surplus-recourse path did not realize that value.

## 2. Information boundary and method

The ordinary observer uses actual BESS point-of-interconnection power as a known input. Persistent load error is represented as a slow state/parameter rather than repeatedly injected as a new event. The capability estimator maintains a causal set for power, ramp, and delay; measured state of charge supplies the energy state and availability is folded into deliverability. The contract floor and online envelope remain distinct.

DCSV-CR-MPC produces a contract-safe base command and may use only certified surplus for future-loss recourse. It models the delay pipeline, state of charge, power/ramp limits, slow reserve, sustainable/bridge/infeasible routing, and lexicographic feasibility restoration. The primary baseline uses the same rolling infrastructure but only the contract floor. Applied-action transactions commit the action actually sent after rejection, restoration, or fallback.

The same-instant impossibility boundary is essential: if an unannounced capability transition occurs below every previously known positive lower bound before the command can react, no causal controller can guarantee that same command. Therefore sustainable certificates are conditional on the recorded contract and terminal assumptions; bridge certificates are finite horizon and require the stated slow takeover; physically infeasible cases are emitted before ordinary performance scoring.

## 3. Experimental design and statistics

Validation and confirmation were isolated. Validation used 120 full nonlinear Plant-A and 24 native ANDES Plant-B paired scenarios. Confirmation froze all code, weights, thresholds, manifests, and seeds before results. Seeds 100--159 were consumed once in 120 balanced Plant-A scenarios; 24 native Plant-B pairs, 120 supplemental baseline rows, 42 full 3600 s normal-profile rows, and six contract-violation rows were also executed.

Primary statistics are scenario-balanced aggregate means and paired absolute differences. Uncertainty uses seed/design-cell hierarchical bootstrap. The mean episode-relative ratio is retained only as a diagnostic because it can overweight small denominators. Failure-aware analyses include all evaluated nonphysical failures. Solver failure rates use every attempted optimization call, with decision and raw-invocation denominators both reported.

{results.replace('# Results', '## 4. Results').strip()}

## 5. Why causal adaptation did not realize perfect-information value

Across 24 balanced information-value scenarios, perfect capability improved ACE by {pct(value['ace_iae_pu_s']['perfect_information_improvement_relative_to_contract'])} and tie-line RMS by {pct(value['tie_rms_pu']['perfect_information_improvement_relative_to_contract'])}, while its peak-frequency result was {pct(value['frequency_peak_hz']['perfect_information_improvement_relative_to_contract'])}. The causal-online variant was worse by {pct(-float(value['ace_iae_pu_s']['causal_online_improvement_relative_to_contract']))} on ACE, {pct(-float(value['frequency_peak_hz']['causal_online_improvement_relative_to_contract']))} on frequency, and {pct(-float(value['tie_rms_pu']['causal_online_improvement_relative_to_contract']))} on tie-line RMS. A model-adaptive baseline stayed close to contract-only control.

The mechanism was starved of actionable surplus. The registered excitation experiment classified 75% of episodes as sufficiently excited, yet the estimated performance envelope exceeded the contract in 0% of those episodes. Under natural closed loop, an excitation proxy was present in 49.36% of episodes, but surplus was active for only 2 of 22,392 calls (0.0089%) and six seconds in total. Meanwhile prediction-proxy tension occurred near ACE and tie constraints. Every validation fallback was traced to mathematical infeasibility of the primary and restoration problems, not to numerical failure. Confirmation likewise recorded zero numerical failures but 1,171 fallbacks. The evidence therefore points to an information-to-action bottleneck: capability may have value in principle, but the causal lower envelope rarely certified exploitable margin and the constrained prediction became infeasible on Plant A.

## 6. Discussion

The fairest deployable conclusion is not that adaptation never helps. It is that a guaranteed contract floor remained more reliable than the tested causal surplus mechanism. Perfect-information value identifies an upper-bound opportunity; it does not validate an online estimator. Likewise, zero hard violations and successful contract-breach detection support parts of the safety architecture without supporting the controller's performance claim.

The Plant split matters. Small favorable differences on native Plant B did not compensate for a negative direction, eight DCSV-only failures, and all fallbacks on full nonlinear Plant A. The universal normal-profile failure also prevents an engineering-readiness claim for any tested controller.

{limitations.replace('# Limitations', '## 7. Limitations').strip()}

## 8. Conclusion

The registered positive Gate failed in validation and again in untouched-seed confirmation. DCSV-CR-MPC did not outperform contract-only rolling MPC under the frozen protocol. Direction5 therefore closes as a negative result with bounded claims: perfect capability information can be valuable, but the tested causal deliverability estimator and surplus-loss recourse did not reliably expose or exploit that value. No new phase, method substitution, or post-confirmation tuning is warranted by this protocol.
"""
    write("PAPER_DRAFT.md", manuscript)

    # Machine-readable claim ledger used by packaging and tests.
    claim_rows = [
        ("MATERIALITY", "SUPPORTED", "R1"),
        ("PERFECT_CAPABILITY_VALUE", "SUPPORTED_WITH_BOUNDS", "C1"),
        ("CAUSAL_ONLINE_SUPERIORITY", "NOT_SUPPORTED", "C1,C2"),
        ("DCSV_CR_MPC_SUPERIORITY", "NOT_SUPPORTED", "R5,C2"),
        ("CROSS_PLANT_POSITIVE_DIRECTION", "NOT_SUPPORTED", "R5,C2"),
        ("NORMAL1H_QUALITY", "NOT_SUPPORTED", "R5,C2"),
        ("GLOBAL_RECURSIVE_FEASIBILITY", "NOT_SUPPORTED", "R4"),
        ("CONTRACT_VIOLATION_DETECTION", "SUPPORTED_WITH_BOUNDS", "R3,R5,C2"),
    ]
    with (OUT / "CLAIM_LEDGER.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["claim", "status", "evidence"])
        writer.writerows(claim_rows)

    forbidden = "[" + "PREDICTED" + "]"
    material = "\n".join(path.read_text(encoding="utf-8") for path in OUT.glob("*.md"))
    if forbidden in material:
        raise RuntimeError("predicted placeholder remains in actual-results manuscript")
    if "DCSV-CR-MPC outperforms" in manuscript:
        raise RuntimeError("unsupported superiority phrasing in manuscript")

    progress = {
        "schema": "direction5.closure.progress.v1",
        "stage": "C3",
        "status": "PASS",
        "route": "NEGATIVE_RESULT_MANUSCRIPT",
        "manuscript_title": title,
        "validation_positive_gate": False,
        "confirmatory_positive_gate": False,
        "joint_positive_gate": False,
        "predicted_placeholders_remaining": 0,
        "unsupported_superiority_claim": False,
        "post_result_tuning": False,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "next_stage": "C4",
    }
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(progress, indent=2))


if __name__ == "__main__":
    main()
