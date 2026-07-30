# Phase C Decision Ledger

## Governing goal

- Authoritative goal: `research/phase_c_full_rebuild_and_method_completion/CODEX_GOAL.md`
- SHA256: `6909f035b3082ffd533b1c22c2e7b806d8dd4a33ca624b953f27322397054b56`
- Execution order: C0 through C9 without an inter-stage approval pause.

## C0 baseline decision

- Phase B2 evidence is retained read-only at commit `5953ffcf71a641581364e0684b982852def4421c`.
- Tag `direction5-phase-b2-reviewed-invalidated` identifies that frozen evidence.
- The Phase B2 decision `PROBLEM_NOT_MATERIAL` is withdrawn as a valid scientific conclusion because the Phase C expert review identified frequency-unit, Oracle, information-fairness, energy, shared-capability and evaluation-horizon defects.
- No Phase B2 result file will be overwritten. Phase C uses separate source, configuration, result, figure, log and artifact paths.

Further Gate decisions are appended only from preregistered validation/final evidence.

## C0 Gate — PASSED

- Frozen ZIP SHA256 and CRC verified; archive member count is 164.
- All 20 Phase C launch-package files matched their declared sizes and SHA256 values.
- The complete repository baseline was enumerated without overwriting Phase B2 evidence.
- Frozen baseline regression: 649 passed, 2 pre-existing numerical-accuracy warnings.
- A clean temporary virtual environment installed the repository editable with no dependency substitution and imported `d5freq` successfully.
- No fatal source-baseline gap was found. C1 is authorized.

## C1 Gate — PASSED

- Locked question: external-I/O-only detection of control-relevant IBR capability changes before physical control harm, followed by safe multi-area responsibility reallocation.
- Verified corpus: 50 records, 45 formal peer-reviewed/standard sources, 27 later than 2021, zero fabricated records.
- Novelty is restricted to the intersection of capability-set change, `Tdet<Tcrit`, unknown-load separation, ACE/tie-line responsibility and Gate-selected safe control; individual black-box, DeePC, adaptive MPC and dual-control components are not claimed novel.
- H1–H5 and all falsification thresholds are locked before model validation and final seeds.
- C2 physical/model rebuild is authorized.

## C2 Gate — PASSED WITH DECLARED FIDELITY BOUNDARY

- Frequency is internally per-unit and reported in hertz; the initial RoCoF relative error is `1.85e-16`.
- Mechanical GRC, reserve anti-windup, and jointly constrained BESS PFR+SFR are explicit. The maximum 1000-step energy residual is `1.78e-15 MWh`; no SoC projection is used.
- Transparent two-area Plant A and a four-machine/six-bus RMS-network DAE Plant B run successfully.
- ANDES 2.0.0's unmodified Kundur case passed native power flow and time-domain simulation (10 buses, 15 lines, four synchronous machines).
- The controllable Plant B and ANDES reference are explicitly a cross-qualification, not trajectory-identical or EMT/OEM fidelity. C3 validation is authorized.

## C3 Gate — PASSED

- Analytic and central-difference swing/tie Jacobians agree to machine precision.
- All required 0.005/0.01/0.02/0.05 s runs are retained. The selected 0.01 s step differs by at most 0.699% from the 0.005 s reference on the audited metrics.
- An initially incorrect Plant B slack-bus balance sign was detected, recorded, repaired and rerun; Plant A/B now have consistent physical response direction.
- Constraint-boundary and observation-API audits passed. Validation configuration is locked at SHA256 `fbbbf9ee49d112b978909035f90c803cbe6df30f3db0f81b4dbacaf49140294f`.
- C4 current-capability Oracle materiality testing is authorized.

## C4 Gate — PASSED

- All 240 validation episodes are retained; final seeds were not read. O2 solve success was 99.59% on Plant A and 100% on Plant B.
- Scenario-balanced aggregate ratios with seed-within-scenario bootstrap show Plant A improvements of 54.45% frequency IAE and 40.57% ACE IAE, both with positive 95% CI lower bounds.
- Plant B improvements are 76.12% and 60.13%, likewise with positive lower bounds.
- The Oracle is a current-capability, rolling, multi-action nonlinear multiple-shooting local NMPC and is not described as globally/exactly optimal.
- The scientific problem is material on both validated model classes. C5 identifiability timing is authorized.

## C5 Gate — PASSIVE IDENTIFIABLE; C6-A SELECTED

- Validation `P(Tdet<Tcrit)=1.0`, false-alarm rate 0, and source macro-F1 1.0.
- Headroom, ramp and delay each pass the timing condition; offline labels are used only for scoring.
- The unique authorized method branch is `C6-A_SET_ADAPTIVE_MPC`. Safe-dual and structural robust branches are rejected for this run and will not be stacked.
- Final configuration is locked before final seeds at SHA256 `ce54ab4b520e9e7415979403f0a3d0d4b1274969bddf6342b3957c1dea816838`.

## C6-A Gate — PASSED CONDITIONALLY

- Only set-adaptive MPC was implemented. Its public API has no true-regime, hidden-parameter, true-load, SoC or future-information input.
- Validation success and audited set coverage are 100% on both Plants. Relative frequency/ACE IAE improvements over fixed allocation are 48.6%/50.6% on Plant A and 27.6%/84.9% on Plant B.
- Set coverage, recursive feasibility and constraint safety are conditional on the explicitly stated noise, disturbance and SG-backup authority assumptions. No unconditional guaranteed-safe claim is made.
- C7 preregistered experiment lock and dry run are authorized.

## C7 Gate — PASSED AND LOCKED

- The final manifest contains all 30 known and 50 OOD seeds on both Plants (160 plant/scenario cases), with deterministic scenario and SG-capability assignment.
- Eight required/optional method statuses, failure classes, metrics, ablations, statistics and compute budget are frozen.
- A development-seed dry run and final-seed firewall tests passed. Final results had not been observed at lock time.
- C8 is authorized; from its first final result onward, controller/configuration/threshold edits are prohibited.
