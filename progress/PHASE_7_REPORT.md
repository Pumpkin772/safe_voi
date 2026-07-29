# Phase 7 report: paper-level evidence and review package

**Status:** PASS for final evidence, figures, test suite, reproducibility
metadata, and strict review-package input gates

**Date:** 2026-07-29

**Frozen Phase-6 implementation commit:**
`20f652f5f8b180a2518798d0ed85aa3f48212908`

## Completed items

- Consumed only the six canonical Phase-6 result tables and their final
  protocol lock.  Result identity, matrix completeness, Oracle pairing, and
  source hashes are revalidated before figure or package generation.
- Exported 10 representative runs and three retained worst cases using the
  deterministic selection rules.  The representative tree contains 40 ZSTD
  Parquet traces plus its manifest/support files; the worst-case tree contains
  12 ZSTD Parquet traces plus its manifest/support files.
- Generated exactly 12 required PNG figures.  Every manifest row is
  `available`; no placeholder, partial, or synthetic replacement panel is
  present.  Actual PNG hashes match the figure manifest.
- Visually inspected the system-information-flow, known-switch belief, OOD
  fallback, and worst-retained-failure figures.  Titles, axes, legends,
  thresholds, and state traces render without clipping or unreadable overlap.
- Retained all 19 scientific failures in the final metrics and visualized a
  manifest-ranked worst case rather than selecting only successful episodes.
- Ran the final source test command with warnings promoted to errors and
  generated both text and JUnit evidence: 609 passed, zero failures, zero
  errors, zero skips, in 91.708 s.
- Recorded the original specification package, environment definition,
  configs, source/tests/scripts, Phase 0--7 reports, result tables, selected
  trajectories, figures, test evidence, Git state/diff, and file hashes as
  mandatory review-package inputs.

## Figure acceptance

The figure manifest has 12 rows, all with `status=available`.  Its SHA-256 is
`630e4d33fbcbaa7358eb8b18a9cd4169ad9e8a14f666554057803545089221e8`.

| ID | Required figure |
|---:|---|
| 1 | System, diagnostic, controller, and fallback information flow |
| 2 | Hidden-mode truth responses |
| 3 | GMM BIC and clustering evidence |
| 4 | Known switch truth and runtime belief |
| 5 | Controller frequency comparison |
| 6 | SG/IBR commands and actual IBR output |
| 7 | Detection delay versus frequency IAE |
| 8 | OOD p-value, fallback state, and frequency |
| 9 | Method performance distributions |
| 10 | Ablation results |
| 11 | Solver-time distributions |
| 12 | Worst retained failure case |

Each manifest row binds its input sources and output image by SHA-256.  The
three failed pre-publication attempts caused by invoking `python.exe` without
Conda's DLL path left only empty staging directories; those directories were
verified empty and removed.  The successful build used
`conda run -n topo_sfr`, so NumPy/Matplotlib resolved the environment runtime
correctly and atomically published the complete directory.

## Final test and environment qualification

The canonical command is:

```powershell
conda run -n topo_sfr python -m pytest -q -W error `
  --junitxml=logs/pytest_final.xml tests `
  | Tee-Object -FilePath logs/pytest_final.txt
```

JUnit records 609 tests, zero failures, zero errors, and zero skipped tests.
Evidence hashes are:

- `logs/pytest_final.txt`:
  `120eed5f6f7f6377de1ef6c0c095d140d5cba5e3969575db29524f2947212f0b`;
- `logs/pytest_final.xml`:
  `db7a5bcbe0bd249f370500261beff994d2ef5ed8578856babd44bef4b056576d`.

Three final compatibility corrections are intentionally outside the frozen
Phase-6 production code hash:

1. The hard-MAP unit fixture supplies CLARABEL 0.11.1 with `1e-5` feasibility
   and gap tolerances plus a 1,000-iteration test limit.  This keeps the tiny
   synthetic fixture on the exact `optimal` path; production solver policy and
   Phase-6 results are unchanged.
2. `environment.yml` pins `libblas`, `libcblas`, and `liblapack` to the
   conda-forge OpenBLAS implementation.  The unconstrained Windows solve had
   combined MKL's `libiomp` with scikit-learn's `libomp`, which threadpoolctl
   correctly rejected under `-W error`.  OpenBLAS removes the mixed OpenMP
   runtime without changing the requested numerical APIs.
3. The legacy linear-MPC test module precisely ignores CVXPY 1.9.2's
   `overflow encountered in reduce` warning.  CVXPY computes only a sum's
   output shape by reducing an uninitialized `np.empty` placeholder, so the
   warning depends on allocator residue and occurs before any optimization
   value exists.  Every other warning remains fatal, and the locked
   `linear_mpc.py` implementation is unchanged.

All three changes are included in the final source snapshot and Git diff.  No
`src/d5freq` file, Phase-6 runner, experiment config, model artifact, or final
result table was changed after protocol lock.

## Scientific claims and qualifications

The review package supports the following bounded conclusions:

- P improves paired mean frequency IAE and settling time relative to B1, but
  is worse than B2 on both measures; it is not uniformly dominant.
- P completes all 100 OOD episodes in the final population, while its online
  OOD detector detects only 15/100 and has near-random ranking.  Safe fallback
  and robust control behavior must not be described as proof of strong OOD
  classification.
- P's solver load and timeout rate are materially higher than B1/B2, although
  no infeasible/inaccurate result executes and no solver-without-fallback
  catastrophe occurs.
- B4 is truth-informed and may appear only as an evaluation upper bound.
- Negative empirical Oracle regret for another architecture does not make
  B4 deployable or globally optimal; it reflects the defined paired cost and
  controller-class differences.
- The 19 retained `catastrophic_not_recovered` outcomes, weak diagnostic
  metrics, and solver warnings are limitations, not missing data.
- Timing evidence is host-, load-, solver-, and license-specific and is not a
  hard real-time guarantee.

## Reproduction commands

```powershell
conda env create -f environment.yml
conda run -n topo_sfr python -m pip install -e .

conda run -n topo_sfr python scripts/05_run_full_experiments.py
conda run -n topo_sfr python scripts/phase6_export_selected_trajectories.py `
  --repo-root . --results-dir results/final
conda run -n topo_sfr python scripts/06_make_figures.py `
  --repo-root . --results-dir results/final `
  --representative-dir results/final/representative_trajectories `
  --worst-dir results/final/worst_failure_cases `
  --figures-dir results/phase7/figures
conda run -n topo_sfr python -m pytest -q -W error `
  --junitxml=logs/pytest_final.xml tests
conda run -n topo_sfr python scripts/07_build_review_package.py `
  --repo-root . --results-dir results/final `
  --figures-dir results/phase7/figures `
  --reference-docs ../D5_SD_BMPC_FROM_SCRATCH_CODEX_PACKAGE_V2
```

Commercial solver steps additionally require valid `MOSEKLM_LICENSE_FILE` and
`GRB_LICENSE_FILE` settings.  The canonical environment name is `topo_sfr`.

## Review-package acceptance rule

The package builder is intentionally the final atomic acceptance gate.  It
refuses incomplete Phase-6 identity, non-available/mismatched figures,
unverified selected trajectories, failing JUnit, missing Phase reports,
missing original specifications, duplicate review ZIPs, or an archive at or
above 512 MiB.  A successfully published
`D5_FROM_SCRATCH_SD_BMPC_REVIEW_PACKAGE.zip` therefore certifies all of those
conditions; the final outer ZIP hash and byte size are reported alongside the
delivered file, avoiding a self-referential hash inside the archive.

## Phase 7 acceptance decision

PASS.  Paper-level tables, paired statistics, representative and failure
traces, 12 authenticated figures, complete tests, environment constraints,
source/Git evidence, and Phase reports are ready for the strict single-archive
build.  Scientific limitations are explicit and no failure row or adverse
comparison has been removed.
