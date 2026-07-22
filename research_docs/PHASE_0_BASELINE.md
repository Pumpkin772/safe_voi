# Phase 0 implementation baseline

## Authoritative specification

The immutable input specification is the sibling directory
`D5_SD_BMPC_FROM_SCRATCH_CODEX_PACKAGE_V2`. Its
`PACKAGE_MANIFEST.json` was verified before implementation: all 25 listed
files matched their recorded sizes and SHA-256 digests. The implementation is
derived from the mathematical and interface requirements in that package and
does not import its Python reference module at runtime.

## User-approved environment decision

The specification originally requested a newly named Conda environment. On
2026-07-22 the user explicitly selected the existing Python 3.11 environment
`topo_sfr` for this project. `environment.yml` therefore declares that name and
the complete dependency set. The existing environment was audited before use:

- a stale editable installation of an unrelated prior project was removed;
- the old repository path was confirmed absent from `sys.path`;
- all required dependencies were installed and `pip check` passed;
- MOSEK and Gurobi completed independent convex smoke solves.

No solver license file, credential, token, or key may be copied into this
repository or a review package.

## Non-negotiable information boundary

1. The simulator owns hidden-mode truth and may expose it only through an
   evaluation record returned beside the controller-visible measurement.
2. Production controller APIs must not accept a true-mode field, truth index,
   truth name, or mode schedule.
3. Unlabeled identification filenames and controller-side artifacts must not
   encode physical mode names or truth ordering.
4. Hungarian alignment and truth-based metrics belong only in evaluation code.
5. Oracle control is an evaluation-only upper bound and must not be imported by
   the proposed controller.

## Numerical and reproducibility invariants

- All randomness enters through an explicit `numpy.random.Generator`.
- Internal frequency is per-unit; reported frequency and RoCoF use Hz and Hz/s.
- Continuous truth simulation uses RK4 with control-period ZOH.
- All failures and failed episodes are retained and logged.
- Resolved configuration, environment metadata, seeds, and SHA-256 digests are
  saved with generated artifacts.
- No absolute local path is embedded in production configuration or source.

## Phase order

Phases 1 through 7 may start only after the preceding phase's tests and
`progress/PHASE_X_REPORT.md` acceptance evidence are complete. Scientific
performance targets are reported honestly and are never enforced by deleting
failures or tuning test scenarios.
