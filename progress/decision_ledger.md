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
