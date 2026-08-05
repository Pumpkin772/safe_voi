# Results

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
