# Phase 4 report: online native-component belief and OOD diagnosis

**Status:** PASS for implementation and reproducibility, with material diagnostic limitations retained

**Date:** 2026-07-22

**Implementation commit:** `81d558c947cf56c9fcdfcbf65e911e1e03de18b0`

## Completed items

- Implemented equations (40)--(47) as a numerically stable sticky-Markov Bayes
  filter over the frozen six native Phase-3 components.  The update uses the
  exact online ARX history order, Gaussian likelihoods in the log domain,
  log-sum-exp normalization, positive belief/variance floors, per-component
  residuals and NIS, and raw plus normalized entropy.
- Implemented equations (48)--(50) using the minimum standardized residual and
  the finite-sample split-conformal p-value, including calibration ties.
- Implemented the four-state `KNOWN -> SUSPECT -> OOD_ACTIVE -> RECOVERY`
  hysteresis machine with strict threshold comparisons and reset-safe state.
- Added the controller-facing `OnlineModeDiagnostic`.  Its first two samples
  are explicit ARX warm-up records and do not update either the belief or OOD
  state with fabricated residuals.
- Built OOD calibration from all 16 authenticated, known-only
  `ood_calibration` trajectories.  The strict artifact binds 5744 scores to
  the dataset/split manifests, all source-trajectory hashes, the frozen model
  library file and logical hashes, native component IDs, measurement-noise
  variance, variance floor, and score definition.
- Selected hysteresis with leave-one-trajectory-out cross-validation on known
  calibration trajectories only.  OOD trajectories were never used for
  parameter selection.
- Evaluated all 16 fixed public test trajectories and six generated diagnostic
  scenarios: nominal-to-sluggish, nominal-to-unavailable, load-step proxy,
  increased noise, asymmetric-limit OOD, and time-varying-delay OOD.  Four
  distinct authenticated excitation inputs were used for generated scenarios.
- Enforced a runtime information barrier: the truth-free runtime Parquet and
  manifest are saved and hashed before private metadata or the training-only
  component/reference mapping is opened.  The runtime file is re-hashed after
  evaluation and must remain unchanged.
- Kept the frozen K=6 representation authoritative.  A many-to-one K6-to-K4
  mapping is used only after the barrier to express evaluation metrics; it is
  never returned to the diagnostic or a controller.
- Added probability, switch, false-alarm, OOD, reliability, scenario and
  epsilon-sensitivity metrics, together with plots regenerated from persisted
  tables.
- Saved expanded configuration, Git provenance, Python/package/solver
  versions, all random seeds, model/config hashes, and hashes of every source
  file that materially generates the Phase-4 outputs.
- Extended the mathematics-to-code map through equations (40)--(51).

## Acceptance evidence

Canonical commands:

```powershell
conda run -n topo_sfr python scripts/03_calibrate_ood.py

conda run -n topo_sfr python scripts/03_calibrate_ood.py `
  --output-dir artifacts/online_diagnosis_repro_check

$env:LOKY_MAX_CPU_COUNT='1'
conda run -n topo_sfr python -m pytest -W error `
  --cov=src/d5freq `
  --cov-report=xml:progress/phase4_coverage.xml `
  --junitxml=progress/phase4_junit.xml
```

The strict Phase-4 baseline result is **393 passed, 0 failed, 0 errors, 0
warnings**.  Coverage of the source tree present at the Phase-4 commit is
**82%**.  The JUnit and coverage records are retained as
`phase4_junit.xml` and `phase4_coverage.xml`.

The canonical run and independent rerun produced byte-identical calibration
artifacts, truth-free runtime logs, generated trajectories, metric files,
tables, and plots.  Only the timestamp-bearing environment provenance and the
summary/manifest files that hash it differ as expected.

## Frozen calibration and information barrier

The selected values are the predeclared defaults:

| Parameter | Selected value |
|---|---:|
| `alpha_on` | 0.01 |
| `alpha_off` | 0.10 |
| `L_on` | 3 steps |
| `L_off` | 5 steps |
| variance floor | `1.0e-8 pu^2` |

The search covered 99 valid combinations over `alpha_on`, `alpha_off`,
`L_on`, and `L_off`.  Its population and scoring unit were known-mode
calibration trajectories and leave-one-trajectory-out folds.  Calibration,
test, and generated OOD hashes are pairwise disjoint.

The state implementation follows the four-state diagram literally: the
`L_on`-th consecutive low p-value enters `SUSPECT`, and the next continuing
low p-value enters `OOD_ACTIVE`; similarly, the `L_off`-th high value enters
`RECOVERY`, and the next continuing high value returns to `KNOWN`.  This is
one sample more conservative than a possible direct reading of equation (51),
and is deliberately locked by tests and recorded in the hysteresis-selection
artifact.

The frozen evaluation-only component mapping is:

| Native component | Reference class used only for metrics |
|---:|---|
| 0 | derated |
| 1 | derated |
| 2 | unavailable |
| 3 | nominal |
| 4 | derated |
| 5 | sluggish |

Component 1 has mixed train evidence (`6` derated versus `5` nominal), and
component 2 mixes sluggish/unavailable evidence (`6` versus `24`).  These
facts help explain the probability-calibration and false-alarm limitations;
no post-hoc merge or refit was performed.

## Canonical diagnostic results

Known-mode probability metrics over 7536 valid-update samples are:

| Metric | Value |
|---|---:|
| Accuracy | 0.8559 |
| Macro-F1 | 0.8404 |
| Brier score | 0.2370 |
| Negative log likelihood | 0.4875 |
| Expected calibration error | 0.0954 |

Both generated known-mode switches were detected without censoring:

| Transition | Detection delay |
|---|---:|
| nominal -> sluggish | 2.5 s |
| nominal -> unavailable | 7.5 s |

The mean and median detected delay are both 5.0 s.  On the fixed public test
set alone, macro-F1 is 0.8599.  The generated nominal-to-sluggish scenario has
only 0.5014 accuracy despite satisfying the consecutive-probability switch
detection rule; this distinction is retained rather than summarized away by
the detection event.

OOD results are:

| Metric | Value |
|---|---:|
| AUROC | 0.5576 |
| AUPRC | 0.6161 |
| Detected OOD events | 1 / 2 |
| Censored OOD events | 1 / 2 |
| Detected delay | 21.5 s |

The time-varying-delay OOD event was detected at 111.5 s after a 90.0 s
onset.  The asymmetric-limit event remained censored through the 90.0 s
post-onset observation window.  Neither event was already active at onset, so
no pre-existing false alarm is credited as a zero-delay detection.

## False alarms and epsilon sensitivity

Using the predeclared `epsilon_switch=0.002`, no-switch known episodes contain
24 sustained wrong-MAP events across 3231 s exposure: 26.74 events/hour, with
9 of 18 episodes affected.  The single Phase-4 load-step proxy episode has a
brief four-sample derated classification after the step and therefore counts
as one false alarm under the strict `L_fa=3` definition; its window rate is
1/1.  The overall load-step scenario accuracy is nevertheless 0.9889.

The declared sensitivity sweep was not used to alter the main result.  It
shows the expected persistence trade-off: at `epsilon_switch=0.0005`,
macro-F1 rises to 0.8532 and false alarms fall to 21.17/hour, with no
load-window event, while both switch events remain detected with the same
mean delay.  Adopting that value after observing test behavior would be
post-test tuning, so the authoritative value remains 0.002.

## Required artifacts and hashes

The canonical directory `artifacts/online_diagnosis/` contains 23 top-level
files plus six generated trajectory Parquets.  Principal SHA-256 values are:

- model library: `a493380e29efe4879c955f2a3d9891a155fb818f38ffe99c12181616c449bf22`;
- calibration artifact: `190fd05d3d0a449a46770112a0707d33fae16fd118b7c16be44a06916d531141`;
- truth-free runtime log: `56404c9cf7a634cda0d6c32b3c9ef8659e3496bf2ee27801f1ef3c3c68d57d0e`;
- runtime manifest before truth read: `c2469bf8a41944bfe728637c91ce97fee391f4e25e8486ea0b28ebaa60ff9f7a`;
- evaluation metrics: `0b429511e4fb7c76cc68daec9ef97b014c8e6a0f8389394bcb030702ac838065`;
- canonical artifact manifest: `59c118ce0c7a53e7ddea3e06306429e517df57f45f52cfe8b76382b24a571eba`.

Key files include the strict calibration artifact/residual table, runtime-only
Parquet/manifest, evaluation-only truth join and mapping, split-integrity
record, CV table and selected hysteresis, full metrics, reliability and
scenario tables, epsilon sensitivity, three diagnostic plots, expanded YAML,
and reproducibility provenance.

## Qualifications carried into Phase 5/6

1. The native six-component library remains scientifically authoritative.
   Phase 5 must use all six beliefs and must not consume the evaluation-only
   K6-to-K4 mapping.
2. Macro-F1 remains below the approximate 0.90 research-quality target, and
   the false-alarm rate is high.  The mixed native components and use of a
   memoryless Gaussian innovation likelihood are plausible contributors.
3. Minimum-across-mode standardized residual is weak for the two specified
   OOD mechanisms: AUROC is only slightly above random and one event is
   censored.  This is a substantive limitation of the prescribed score, not a
   reason to retune against OOD test data.
4. The Phase-4 load-step check uses an externally imposed frequency proxy, not
   a coupled grid/load simulation.  The full S1 matrix at `+/-0.02`, `+/-0.04`,
   `+/-0.06`, and `+/-0.08 pu` must be tested in Phase 6 before claiming
   disturbance/mode separation.
5. Phase-3 frequency/RoCoF q95 bounds propagate IBR power-model error through
   the known grid dynamics but do not include complete closed-loop Kalman or
   controller error.  Phase 5 must preserve that limited interpretation.

## Phase 5 entry decision

The implementation, truth-isolation, calibration-disjointness, numerical, and
reproducibility gates are open.  Phase 5 may use the six-component posterior,
normalized entropy, and four-state OOD output.  `SUSPECT` must expand the
robust risk set, while both `OOD_ACTIVE` and `RECOVERY` must keep the
controller in a safe fallback/recovery path.  The low OOD discrimination and
high false-alarm rate must remain visible in closed-loop fallback statistics.
