# Limits of Causal Online Deliverability Adaptation for Black-Box IBRs in Multi-Area Secondary Frequency Control

## Abstract

Black-box inverter-based resources can deliver less power and ramp capability, or more delay, than a dispatch model assumes. We study whether public point-of-interconnection measurements can separate net-load disturbance from device execution mismatch well enough to improve multi-area secondary frequency control. The frozen DCSV-CR-MPC combines a contract-safe base command with causal set-membership capability estimation and future surplus-loss recourse; the primary comparator is an otherwise matched contract-only rolling MPC.

An independent audit exactly reproduced 262 archived statistics and 19 registered Gate decisions. Validation used 120 full nonlinear Plant-A scenarios and 24 native ANDES Plant-B scenarios. A separately locked, one-time confirmation used the previously untouched seeds 100--159 in 120 Plant-A scenarios, plus 24 native Plant-B scenarios, 42 genuine 3600 s method runs, and six contract-violation runs. In confirmation, DCSV-CR-MPC reduced the success rate by 7.48 percentage points, passed 0/3 core performance Gates, and required 1,171 fallbacks in 20,227 optimization decisions. On both-success pairs, improvements relative to contract-only MPC were 0.60% for peak frequency deviation, 2.68% for ACE IAE, and -10.06% for tie-line RMS; all registered lower confidence bounds failed the positive criterion.

Perfect capability information retained value for ACE and tie-line control, but the causal-online variant was worse than the contract controller, yielding perfect-minus-online gaps of 45.91% for ACE and 63.78% for tie-line RMS. Natural closed-loop excitation almost never converted the online envelope into usable surplus: only 2 of 22,392 DCSV calls activated surplus. All 1,171 confirmatory fallbacks and all 1,021 validation fallbacks were attributable to primary/restoration mathematical infeasibility rather than numerical solver failure. The positive Gate did not hold in either validation or confirmation. We therefore report a bounded negative result: perfect capability can matter, but this causal estimator--recourse realization did not outperform a contract-only MPC under the registered plants, events, horizons, and safety standards.

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

## 4. Results

## Registered primary comparison

The primary result compares frozen DCSV-CR-MPC against contract-only rolling MPC. Positive numbers indicate lower cost for DCSV-CR-MPC. The main estimator is the frozen causal set-membership deliverability estimator; perfect capability is evaluation-only. Physical infeasibility is classified before controller scoring.

| Metric | Validation improvement | Validation lower bound | Confirmation improvement | Confirmation lower bound | Gate passed in both? |
|---|---:|---:|---:|---:|---|
| Peak |frequency| | 0.23% | -0.77% | 0.60% | -0.18% | No |
| ACE IAE | 3.21% | -4.59% | 2.68% | -5.65% | No |
| Tie-line RMS | -9.07% | -14.75% | -10.06% | -16.69% | No |

The success deficit was 2.73 percentage points in validation and 7.48 points in confirmation, exceeding the registered 2-point limit both times. Confirmation contained 84 both-success pairs, 8 pairs where only DCSV-CR-MPC failed, 0 pairs where only contract MPC failed, 15 pairs where both failed, and 37 pre-certified physically infeasible scenarios. No failed episode was removed or relabeled as not evaluated.

## Plant and condition structure

Plant A was the complete nonlinear simulation and Plant B was the native ANDES Kundur model. The paired frequency absolute difference was -0.177817 Hz on Plant A and +0.000051 Hz on Plant B, so the required cross-plant positive direction did not hold. Plant B had 24/24 successes for each primary method, whereas Plant A contained all eight DCSV-only failures and all confirmatory fallbacks.

On Plant A, the known-condition success rates were 78.57% for contract MPC and 64.29% for DCSV-CR-MPC; OOD rates were 85.37% and 80.49%, respectively. DCSV fallbacks were 501 (known) and 214 (OOD), versus 35 and 55 for contract MPC. On Plant B both methods achieved 100% success in known and OOD groups with small, mixed metric differences. These results do not support an OOD or cross-plant advantage.

## Physical-domain accounting

Confirmation included 84 sustainable, 23 bridge, and 37 physically infeasible scenario pairs. Contract/DCSV successes were 77/71 in sustainable and 15/13 in bridge domains. Physically infeasible cases were reported separately, with zero hard violations for both methods, and were not counted as ordinary controller failures. Bridge claims remain finite-horizon only; no slow takeover is inferred where none was modeled.

## Solver and fallback accounting

Across all confirmation tasks, 20,227 optimization decisions caused 21,400 solver invocations. The accounting identity includes 2 restoration calls and 1,171 fallback decisions. There were 0 numerical failures and 29 accuracy warnings; the 99th-percentile solve-time fraction was 0.277 of the control period. Thus real-time and numerical-failure Gates passed, but mathematical feasibility and fallback Gates did not.

## Normal-profile and contract-violation evidence

Each of seven methods was run on six full 3600 s synthetic registered profiles. All seven failed the frequency-quality Gate. DCSV-CR-MPC reached a 2.290706 Hz peak, 0.906454 Hz RMS, and 322 fallbacks; the evaluation-only perfect-capability oracle also failed, with a 1.645819 Hz peak. These profiles are synthetic AR(2)+multi-sine traces, not public measured load data, so the result is a model/protocol boundary rather than a field-performance estimate.

All six separate contract-violation episodes were detected (27--90 detection calls per episode), recovered terminally, and had zero fallbacks and hard violations. This supports violation detection/separation under those tests, not universal post-breach safety.

## 5. Why causal adaptation did not realize perfect-information value

Across 24 balanced information-value scenarios, perfect capability improved ACE by 6.68% and tie-line RMS by 11.77%, while its peak-frequency result was -1.40%. The causal-online variant was worse by 39.24% on ACE, 18.74% on frequency, and 52.01% on tie-line RMS. A model-adaptive baseline stayed close to contract-only control.

The mechanism was starved of actionable surplus. The registered excitation experiment classified 75% of episodes as sufficiently excited, yet the estimated performance envelope exceeded the contract in 0% of those episodes. Under natural closed loop, an excitation proxy was present in 49.36% of episodes, but surplus was active for only 2 of 22,392 calls (0.0089%) and six seconds in total. Meanwhile prediction-proxy tension occurred near ACE and tie constraints. Every validation fallback was traced to mathematical infeasibility of the primary and restoration problems, not to numerical failure. Confirmation likewise recorded zero numerical failures but 1,171 fallbacks. The evidence therefore points to an information-to-action bottleneck: capability may have value in principle, but the causal lower envelope rarely certified exploitable margin and the constrained prediction became infeasible on Plant A.

## 6. Discussion

The fairest deployable conclusion is not that adaptation never helps. It is that a guaranteed contract floor remained more reliable than the tested causal surplus mechanism. Perfect-information value identifies an upper-bound opportunity; it does not validate an online estimator. Likewise, zero hard violations and successful contract-breach detection support parts of the safety architecture without supporting the controller's performance claim.

The Plant split matters. Small favorable differences on native Plant B did not compensate for a negative direction, eight DCSV-only failures, and all fallbacks on full nonlinear Plant A. The universal normal-profile failure also prevents an engineering-readiness claim for any tested controller.

## 7. Limitations

- The confirmatory evidence covers one full nonlinear two-area Plant A and one native ANDES Kundur Plant B, not hardware or field deployment.
- The six 3600 s profiles are synthetic registered AR(2)+multi-sine traces. They are genuine full simulations, but they are not measured public load records, and every method failed their frequency-quality Gate.
- The perfect-capability comparison is evaluation-only. Its value does not imply that the information is causally available to an ordinary controller.
- The causal set-membership estimator had adequate excitation in 75% of a dedicated 40-episode protocol, but its performance envelope never exceeded contract in that protocol and almost never yielded usable surplus in natural closed loop.
- Binding-constraint indicators are primal-proximity diagnostics rather than optimizer dual multipliers.
- The theorem rules out same-instant guarantees after an unannounced drop below every known positive floor. Conditional recourse and terminal certificates apply only under their recorded assumptions; bridge claims are finite horizon.
- The result is specific to the frozen DCSV-CR-MPC realization, registered weights, horizons, plants, scenarios, and safety Gates. It is not an impossibility proof for all adaptive or robust MPC methods.
- Confirmation consumed seeds 100--159 once under the sealed lock. No post-result retuning or repeat confirmation is permitted.

## 8. Conclusion

The registered positive Gate failed in validation and again in untouched-seed confirmation. DCSV-CR-MPC did not outperform contract-only rolling MPC under the frozen protocol. Direction5 therefore closes as a negative result with bounded claims: perfect capability information can be valuable, but the tested causal deliverability estimator and surplus-loss recourse did not reliably expose or exploit that value. No new phase, method substitution, or post-confirmation tuning is warranted by this protocol.
