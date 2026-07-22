# Phase 3 report: unlabeled offline mode discovery

**Status:** PASS, with reported research-quality limitations

**Date:** 2026-07-22

**Implementation commit:** `2a0b75581b64ea1cffea3ccc9f458281f677d60c`

## Completed items

- Implemented deterministic, paired identification excitation using PRBS,
  band-limited random, multisine, and step families. Command magnitude/rate
  and imposed frequency magnitude are audited before and after simulation.
- Implemented an independent continuous RK4 IBR identification bench. Each
  trajectory has one fixed simulator-private mode, while the returned object
  contains only opaque ID, time, command, frequency, and measured power.
- Generated exactly 40 complete trajectories per known simulator mode and
  split complete trajectories 24/8/4/4 into train, validation,
  OOD-calibration, and test sets. Paired modes receive byte-identical command
  and frequency inputs and always share the same split.
- Physically separated public Parquet trajectories/manifests from private
  evaluation metadata. The public loader authenticates the manifest chain,
  schemas, IDs, hashes, split counts, missing/extra files, and symlink/path
  boundaries without opening the private tree.
- Implemented equations (17)–(26) and (76)–(79): the fixed second-order ARX
  convention, seven-parameter ridge fit, literal raw-trajectory `N_e - 7`
  residual denominator, one-step prediction, true open-loop rolling
  validation, and exact five-state realization.
- Implemented equations (27)–(30), assembling the exact ten-state joint
  grid/ARX predictor with shared `[u_sg, u_ibr]` inputs.
- Implemented training-only eight-dimensional features
  `[theta_1,...,theta_7,log(sigma^2+epsilon)]`, a frozen training scaler, and
  GMM+BIC selection for every configured `K=1,...,6`. PCA is used only to
  render the two-dimensional parameter plot.
- Implemented equation (83)'s pooled cluster refit and equation (84)'s robust
  power, upward-rate, and downward-rate capability estimates without crossing
  trajectory boundaries.
- Assigned validation trajectories with the frozen scaler/GMM and saved
  per-component, per-lead RMSE, MAE, and q95. IBR power-model errors are also
  propagated through the exact known grid error dynamics to frequency and
  RoCoF units.
- Added strict `d5freq.mode_library.v2` persistence. Every discovered component
  stores immutable q95 sequences for power `[pu]`, frequency `[Hz]`, and RoCoF
  `[Hz/s]`, plus observed capability bounds. For the selected six-component
  library, the sticky prior has diagonal `0.99` and every off-diagonal entry
  `0.002`, matching `Pi_ii=1-(K-1) epsilon_sw`.
- Kept private-label loading, Hungarian alignment, ARI/NMI/macro-F1, and the
  confusion matrix entirely under `evaluation/`. They execute only after the
  label-free model library and artifacts have been written and hashed.
- Added a diagnostic-only GMM covariance-regularization audit that cannot
  create or overwrite a model library. It is explicitly marked
  `authoritative_model_selection=false`.
- Extended the mathematics-to-code map through equations (17)–(30), (38)–(39),
  and (76)–(84).

## Acceptance evidence

Canonical commands:

```powershell
conda run -n topo_sfr python scripts/01_generate_id_data.py `
  --config configs/base.yaml `
  --modes-config configs/modes_known.yaml `
  --output-dir artifacts/identification_data

conda run -n topo_sfr python scripts/02_discover_modes.py `
  --config configs/base.yaml `
  --data-dir artifacts/identification_data `
  --output-dir artifacts/mode_discovery

conda run -n topo_sfr python scripts/phase3_gmm_regularization_sensitivity.py

$env:LOKY_MAX_CPU_COUNT='1'
conda run -n topo_sfr python -m pytest -W error `
  --cov=src/d5freq `
  --cov-report=xml:progress/phase3_coverage.xml `
  --junitxml=progress/phase3_junit.xml
```

Final strict result: **284 passed, 0 failed, 0 errors, 0 warnings**. Source
coverage is **85%**. JUnit and coverage XML are retained as
`phase3_junit.xml` and `phase3_coverage.xml`. `compileall`, `git diff --check`,
`pip check`, package import, and strict artifact-hash verification passed.

The complete discovery command was run twice into independent directories.
All 13 hashed label-free files, the private metrics JSON, and the confusion
matrix PNG were byte-identical across both runs.

## Identification-data evidence

The canonical dataset contains 160 trajectories:

| Split | Total trajectories | Per private reference mode |
|---|---:|---:|
| train | 96 | 24 |
| validation | 32 | 8 |
| ood_calibration | 16 | 4 |
| test | 16 | 4 |

All 160 generation audits passed. No failed trajectory was deleted. Observed
audit extrema were:

- maximum absolute command: `0.0552 pu` (limit `0.06 pu`);
- maximum command rate: `0.03 pu/s` (limit `0.03 pu/s`);
- maximum absolute imposed frequency deviation: `0.092 Hz` (limit `0.10 Hz`);
- minimum command standard deviation: `0.0162518 pu`;
- minimum frequency standard deviation: `0.0214582 Hz`;
- maximum ARX regression condition number: `6.9860e4` (limit `1.0e10`).

Dataset hashes:

- logical public dataset:
  `0f7dec05b2dd752bbb0d6d1f849908cfc8190a024888441d25ceded924877ffc`;
- public manifest file:
  `a354b86dcd860ade0088ab00668302af4884f84141e6abdd8ae2caf1b8ca234f`;
- private evaluation metadata:
  `a9aa7ea016ae3742b014ed74efd6181b8604e5968fa8fa9d4ff382c4811d05c1`.

## Canonical BIC result

The authoritative, preconfigured main chain uses full covariance,
`n_init=20`, and `reg_covar=1.0e-5`. Its complete training-only BIC table is:

| K | BIC | Delta from minimum | Converged |
|---:|---:|---:|:---:|
| 1 | 1149.1824 | 1492.5068 | yes |
| 2 | 458.2207 | 801.5451 | yes |
| 3 | 49.6520 | 392.9764 | yes |
| 4 | -169.9255 | 173.3989 | yes |
| 5 | -319.3610 | 23.9634 | yes |
| 6 | **-343.3244** | **0** | yes |

BIC therefore selected **six**, and the selection reached the configured
upper boundary. The native component sizes were:

| Component | Train episodes | Frozen validation episodes |
|---:|---:|---:|
| 0 | 6 | 2 |
| 1 | 11 | 4 |
| 2 | 30 | 10 |
| 3 | 19 | 6 |
| 4 | 12 | 4 |
| 5 | 18 | 6 |

Every component has independent validation evidence. Across the six
components, validation power-bound coverage is `0.9384`–`0.9935` and
directional rate-bound coverage is `0.9819`–`0.9926`. At lead 20, the largest
component-wise q95 values are `0.01144 pu` power, `0.04341 Hz` propagated
frequency, and `0.03189 Hz/s` propagated RoCoF. All 15 pairwise
distinguishability values are positive; the minimum is approximately
`1.1285e4` on the common public validation regressor set.

## Evaluation-only diagnostics

Private metadata contains four simulator reference modes, while the frozen
main result contains six discovered components. The mismatch is retained and
reported; no component was merged, renamed, or refit using truth:

- discovered component count: `6`;
- private reference class count: `4`;
- count match: `false`;
- ARI: `0.6441679`;
- NMI: `0.7492125`;
- macro-F1: `0.8224728`;
- unmatched discovered component IDs after rectangular Hungarian evaluation:
  `0` and `1`.

The macro-F1 is below the research-quality target of approximately 0.90. That
target is not a hard gate and was not used to alter the selected model.

The frozen model-library SHA-256 is:

```text
a493380e29efe4879c955f2a3d9891a155fb818f38ffe99c12181616c449bf22
```

The same digest appears before and after private evaluation. The full
label-free hash manifest has SHA-256
`197c8dcaf0c343ca07d660ff42d9965747a55972cf7b7e4b018fc23b98b2536c`.

## Required artifacts

Generated under `artifacts/mode_discovery/` and ignored by Git:

- `mode_library.json`;
- `scaler.json`;
- `gmm.pkl`;
- `bic_table.csv`;
- `episode_features.parquet`;
- `cluster_assignments.csv`;
- `mode_model_metrics.csv`;
- `multi_step_error_quantiles.csv`;
- `distinguishability_matrix.csv`;
- `bic_curve.png`;
- `parameter_embedding.png`;
- `confusion_matrix.png`.

Additional audit files include `label_free_summary.json`,
`label_free_artifact_hashes.json`, `resolved_base_config.yaml`, and
`private_clustering_metrics.json`. Plots are regenerated from serialized tables,
not directly from ephemeral fit state.

## Resolved failures and numerical issues

1. The first real main-chain run selected `K=6`, not the four private reference
   modes. A temporary exploratory increase of `reg_covar` to `1.0e-2` produced
   an interior `K=4` BIC minimum, but it occurred after observing the main
   result and was rejected as an authoritative correction. The base config was
   restored to `1.0e-5`, the complete canonical dataset/config hash chain was
   restored, and the K=6 main result was regenerated. The diagnostic audit now
   records selections `6,5,5,4` for regularizers
   `1e-5,1e-4,1e-3,1e-2` without overwriting the main library.
2. The initial persistence field `multi_step_error_quantiles` had ambiguous
   units and contained power q95 values even though later MPC tightening needs
   frequency and RoCoF bounds. Schema v2 now stores all three quantities with
   units in field names; the compatibility property explicitly means frequency
   q95 in Hz.
3. The first sticky-matrix adapter treated `switch_epsilon` as total switching
   mass and used diagonal `1-epsilon`. The online-diagnosis specification
   defines every off-diagonal entry as `epsilon`; the corrected K=6 matrix has
   diagonal `1-5*0.002=0.99`.
4. An early orchestration draft placed private-label evaluation beside the
   identification pipeline. It was split before acceptance: `identification/`
   is now public-signal-only, while all private reading and Hungarian alignment
   are under `evaluation/` and execute after artifact hashing.
5. The first public loader verified individual Parquet hashes but did not
   authenticate the complete manifest chain or reject orphan files/symlinks.
   It now verifies exact JSON/CSV schemas, duplicate keys and IDs, all logical
   hashes, split counts, every Parquet schema/hash, extra/missing files, and
   resolved path boundaries.
6. Windows joblib physical-core discovery emits an environment-specific warning
   on this host. Strict test commands set `LOKY_MAX_CPU_COUNT=1`; no library
   code mutates process-wide environment variables.

## Qualifications and deferred work

- The selected-K-at-boundary result indicates excitation-family/nonlinear
  substructure or unresolved covariance complexity. Phase 4 must consume the
  six native components exactly as persisted and must not collapse them using
  private truth. The post-hoc K=4 output is non-authoritative.
- Frequency/RoCoF validation errors are the exact known-grid propagation of IBR
  power-model error from the independent resource bench. They do not include a
  separate full closed-loop grid-state estimation error. Phase 5 must preserve
  this interpretation when using them for tightening and report any additional
  empirical closed-loop margin separately.
- Power/rate capability limits are robust external estimates, not simulator
  internal limits. They are intentionally data-dependent and may be
  conservative for excitation-specific components.
- The Phase 2 fixed physical nominal MPC remains only a bootstrap. Phase 5/6
  factories must use discovered ARX models for scientific fixed-model and
  belief-space comparisons.

## Phase 4 entry decision

The Phase 3 gate is open. Phase 4 may implement log-domain sticky-Markov belief
updates and split-conformal OOD detection using the frozen six-component model
library. Calibration must use only the public `ood_calibration` split, remain
disjoint from test trajectories, and keep all true-mode joins in evaluation.
The online diagnostic implementation must accept native component IDs and must
not use the evaluation-only Hungarian mapping to alter belief or OOD scores.
