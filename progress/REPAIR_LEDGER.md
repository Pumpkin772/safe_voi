# Phase C Repair Ledger

## C0-R1 — Baseline verification harness syntax

- Failure class: code.
- Evidence: the initial PowerShell index-verification command used an ambiguous variable followed by `:` and failed before reading or changing project evidence.
- Repair: delimited the interpolated variables explicitly and reran the same hash/size checks.
- Scientific standards changed: no.
- Result: all 20 launch-package entries matched `PACKAGE_INDEX.json` exactly.

## C1-R1 — Crossref partial publication date

- Failure class: data/metadata parser code.
- Evidence: one exact-DOI Crossref record supplied a `published.date-parts` year value of null, causing the first verification pass to stop before writing any literature output.
- Repair: use the first non-null year from `published`, `issued`, `published-online`, or `published-print`, with the Crossref creation year only as an explicitly recorded final metadata fallback.
- Scientific standards changed: no; exact DOI and title-fragment matching remain mandatory.
- Rerun result: parser advanced to exact DOI/title validation, which correctly rejected one miscited CDC DOI.

## C1-R2 — Seed citation DOI correction

- Failure class: metadata/reference.
- Evidence: exact DOI lookup showed `10.1109/CDC40024.2019.9029462` belongs to an unrelated Lyapunov-exponent paper.
- Repair: an independent Crossref title query identified and verified `10.1109/CDC40024.2019.9029522` for “Data-Enabled Predictive Control for Grid-Connected Power Converters.”
- Scientific standards changed: no; the mismatching entry was rejected rather than retained.
- Rerun result: exact matching advanced and rejected a second unrelated DOI before any output was accepted.

## C1-R3 — Koopman-MPC DOI correction

- Failure class: metadata/reference.
- Evidence: `10.1016/j.automatica.2018.08.011` resolved to a change-point detection paper, not the intended Korda–Mezić work.
- Repair: verified the intended paper and replaced the DOI with `10.1016/j.automatica.2018.03.046`.
- Scientific standards changed: no.
- Rerun result: all exact-DOI records passed; the run then stopped on the first official NERC URL because Conda Python could not build its TLS chain.

## C1-R4 — Official-source TLS trust chain

- Failure class: environment/network verification.
- Evidence: `urllib` raised `CERTIFICATE_VERIFY_FAILED` for an official NERC HTTPS document after all DOI metadata had validated.
- Repair: use the maintained `certifi` CA bundle when present, retaining full certificate verification; do not use an unverified SSL context.
- Scientific standards changed: no.
- Rerun result: all 50 records passed; 45 exact-DOI records and five official/preprint URLs were verified, with zero fabricated records.

## C2-R1 — ANDES packaged self-test entry

- Failure class: external-tool packaging.
- Evidence: `python -m andes selftest -q` attempted discovery in `site-packages/tests`, which the 2.0.0 wheel does not contain, and raised `ImportError`.
- Repair: do not weaken validation or fabricate the missing upstream suite. Run the bundled unmodified Kundur case through native ANDES power flow and TDS, and validate the project adapter with project-owned unit tests.
- Scientific standards changed: no; the missing upstream tests remain disclosed.
- Rerun result: Kundur PFlow and 2 s TDS both succeeded; all five C2 project tests passed.

## C3-R1 — Plant B slack-bus imbalance sign

- Failure class: physical model/sign.
- Evidence: the first C3 cross-model run produced negative Plant A but positive Plant B COI response to a positive area-1 load step. The network solve removed the injection mean and the rotor equation then interpreted reference-bus balance as free generation.
- Repair: retain the six-bus algebraic solve for inter-area exchange, explicitly allocate regional load plus signed tie-line exchange across the two machines in each area, and retain intra-area synchronizing torque.
- Scientific standards changed: no; the required sign/trend comparison caught the error before materiality experiments.
- Rerun result: both Plant A and Plant B COI frequency moved negative after a positive load step; eight combined C2/C3 tests passed.

## C4-R1 — NMPC stage-action indexing

- Failure class: code.
- Evidence: the first C4 unit test indexed an already sliced CasADi action vector as a matrix and stopped before any experiment or final seed was run.
- Repair: apply the action penalty directly to the current stage vector.
- Scientific standards changed: no.
- Rerun result: stage-vector indexing passed; the next isolated test exposed missing Windows IPOPT dependency resolution before solver creation.

## C4-R2 — CasADi IPOPT Windows DLL search path

- Failure class: environment/solver loading.
- Evidence: CasADi found the IPOPT plugin DLL but Windows error 126 showed that dependent Conda DLLs were not discoverable.
- Repair: retain the DLL-directory handle and prepend the environment `Library/bin` directory to the process-local PATH, matching the already validated Phase B2 loader pattern.
- Scientific standards changed: no.
- Rerun result: the isolated O2 solve passed with constraint residual below `1e-5`; both C4 unit tests passed.

## C4-R3 — Materiality batch computational timeout

- Failure class: computational implementation, not method/episode failure.
- Evidence: the first 240-episode batch reached the 604 s process limit before writing any partial result. Profiling by inspection identified a repeated solve of the same constant Plant B network matrix at every 0.005 s substep.
- Repair: precompute the fixed reduced-network inverse; formally select 0.01 s, whose retained C3 comparison to the 0.005 s reference has maximum audited error 0.699%; rerun the identical 240 episodes and 180 s horizon.
- Scientific standards changed: no seeds, scenarios, horizons, Gate thresholds or controller parameters changed.
- Rerun result: representative Plant A/B episodes became bounded and all four fair NMPC runs achieved 100% solver success, but O2 remained worse because both predictors used a zero sustained-load estimate.

## C4-R5 — Fair causal load estimator omission

- Failure class: estimator/experimental fairness.
- Evidence: after C4-R4, both controllers still passed a zero load estimate for the full 180 s sustained-imbalance episode. Capability-aware reallocation therefore reacted only to lagged frequency state, while the nominal controller's accidental SG action could dominate.
- Repair: supply both controllers the same causal unknown-input estimate reconstructed from measured frequency derivative, aggregate mechanical/BESS output and tie-line power balance. The estimator never reads the simulator load or a future sample.
- Scientific standards changed: no; validation repair round 1 remains the same round as C4-R4 and changes no scenario, Gate or final data.
- Rerun result: Plant A passed materiality and solver qualification; Plant B then exposed plant-specific predictor mismatch.

## C4-R7 — Prohibited episode-wise ratio statistic

- Failure class: statistical implementation.
- Evidence: the final validation run completed all 240 episodes with qualified O2 solves, but the first summary used the mean and percentile of episode-wise relative ratios. The governing protocol explicitly forbids this as the sole percentage conclusion.
- Repair: reuse the unchanged episode table; compute a scenario-balanced ratio of aggregate sums and a 5000-draw seed-within-scenario bootstrap CI. No simulation, method or threshold is changed.
- Scientific standards changed: no; this corrects the estimator to the preregistered rule and is not a third tuning round.
- Rerun result: corrected aggregate/bootstrap analysis passed materiality on both core metrics for both Plants.

## C4-R6 — Plant-specific Oracle prediction parameters

- Failure class: model mismatch in Oracle qualification.
- Evidence: validation repair round 1 passed solver qualification and Plant A materiality, but Plant B O2 degraded in adequate/scarce SG cases. The shared predictor still hard-coded Plant A inertia `(5,4.5)`, damping `(1,1)` and a dynamic tie coefficient, whereas Plant B aggregation is `(9,10)`, `(0.6,0.6)` with algebraic network tie output.
- Repair: parameterize both O2 and nominal MPC predictors by the public Plant model; use zero dynamic tie coefficient for the Plant B algebraic tie output. Both fair controllers receive the same model constants.
- Scientific standards changed: no; this is validation repair round 2, the final allowed method-performance repair. Final seeds remain unused.
- Rerun result: all 240 episodes completed; Plant B improvements were 76.1% frequency IAE and 60.1% ACE IAE with positive 95% CI lower bounds and 100% O2 solve success.

## C4-R4 — Coarse Oracle actuator model and Plant B rotor integrator

- Failure class: model/numerical/Oracle qualification.
- Evidence: the completed first validation matrix retained 240 episodes, but Plant B trajectories grew to `1e41`, O2 solve success fell to 42%, and Plant A O2 was worse than nominal MPC. The Oracle predictor treated SG power as instantaneous despite mechanical GRC, while Plant B used energy-injecting forward Euler for a lightly damped rotor oscillator.
- Repair: use a semi-implicit rotor-angle update; expose measured aggregate mechanical/BESS power in Plant B's leakage-safe observation; expand both fair MPCs to seven multiple-shooting states with smooth mechanical GRC and BESS actuator dynamics. No hidden state is added to the deployable baseline.
- Scientific standards changed: no; this is validation repair round 1 of the allowed two, with seeds/scenarios/thresholds unchanged.
- Rerun result: bounded Plant B trajectories and qualified solvers; subsequent same-round estimator repair was required before performance interpretation.

## C9-R1 — Solver license environment not exported to pytest

- Failure class: environment/license discovery.
- Evidence: the first full coverage run completed 627 tests but two legacy production-solver tests raised MOSEK `err_missing_license_file`; no Phase C test failed.
- Repair: export the user-provided external `MOSEKLM_LICENSE_FILE` and `GRB_LICENSE_FILE` paths only to the test process and rerun the complete suite. License files and paths are excluded from the review package environment record.
- Scientific standards changed: no.
- Rerun result: complete coverage run passed 629 tests with two retained numerical warnings and 68% repository-wide coverage.

## C5-R1 — Ramp/delay source feature ordering

- Failure class: identification code.
- Evidence: the first unit trace detected the ramp change at the correct time but classified it as delay because both slow ramp and delay maximize correlation at positive lag.
- Repair: classify explicit headroom clipping first, then the measured maximum output-rate signature, then residual time lag.
- Scientific standards changed: no; no C5 experiment had run and the same locked F1 threshold remains.
- Rerun result: noiseless unit traces passed; the first noisy validation matrix then exposed a maximum-rate robustness defect.

## C5-R2 — Noise-sensitive maximum-rate feature

- Failure class: identification statistic.
- Evidence: the first C5 validation run had perfect timing and zero false alarms but macro-F1 0.556 because every noisy ramp trace was labelled delay. A maximum derivative is dominated by isolated measurement noise.
- Repair: use the post-transition 90th-percentile absolute output rate and a 0.009 pu/s threshold, above the development noise derivative scale and below nominal delay-response rates.
- Scientific standards changed: no; timing, false-alarm and macro-F1 criteria are unchanged, and final seeds remain unused.
- Rerun result: validation `P(Tdet<Tcrit)=1.0`, false alarm 0, macro-F1 1.0, with all three mechanisms passing.
