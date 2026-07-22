# Phase 0 report: repository, environment, and deterministic foundation

**Status:** PASS  
**Date:** 2026-07-22  
**Implementation baseline commit:** `56c809ce7c99bbca46e21fa06345860f541cfa1b`

## Scope and approved deviation

Phase 0 establishes an independent repository, a Python 3.11 execution
environment, deterministic utilities, configuration files, audit evidence, and
a runnable test command. The original specification requested a newly named
Conda environment. The user explicitly overrode that detail and selected the
existing environment `topo_sfr`; the repository and source remain entirely new
and independent. `environment.yml` records the full environment so that the
selected environment can be synchronized reproducibly.

## Completed items

- Initialized an independent Git repository with no remote, submodule, or
  workspace symlink.
- Created the `src` package layout, tests, scripts, configurations, artifacts,
  results, research documentation, and progress directories.
- Added explicit configuration loading, recursive immutable merge, resolved
  configuration output, and canonical configuration hashing.
- Added order-independent named seed derivation and explicit
  `numpy.random.Generator` construction without modifying NumPy global state.
- Added SHA-256 helpers for bytes, files, JSON values, directories, and
  manifests.
- Added JSONL logging, structured exception retention, and scientific-value
  serialization.
- Added allowlisted environment metadata export with recursive secret and
  license-field redaction.
- Added repository hygiene tests for local absolute paths, unrelated package
  references, truth-config boundaries, and controller imports.
- Installed the current repository as the only editable project in
  `topo_sfr`.

## Environment evidence

| Component | Verified value |
|---|---:|
| Python | 3.11.15 |
| NumPy | 2.4.6 |
| SciPy | 1.16.3 |
| pandas | 2.3.3 |
| scikit-learn | 1.9.0 |
| CVXPY | 1.9.2 |
| pytest / pytest-cov | 9.1.1 / 7.1.0 |
| MOSEK / Gurobi | 11.2.2 / 13.0.2 |

The complete sanitized package inventory is in `packages_phase0.txt`.
`pip check` reported no broken requirements. A stale editable installation
from an unrelated prior project was found during the initial environment audit,
removed, and verified absent from both editable-package listings and
`sys.path`. No prior-project source is imported or reachable through a `.pth`
entry.

## Solver smoke evidence

A tiny convex QCQP was solved independently through each configured backend.
Console output was suppressed and not persisted, so no license routing data or
credentials enter the repository.

| Solver | Status | Solution check |
|---|---|---:|
| MOSEK | optimal | x = 0.99999235 |
| Gurobi | optimal | x = 0.99990327 |
| CLARABEL | optimal | x = 1.00000000 |

Machine-readable evidence is in `solver_smoke_phase0.json`.

## Tests and static checks

Canonical command:

```powershell
conda run -n topo_sfr python -m pytest -q
```

Final Phase 0 result: **25 passed, 0 failed, 0 errors**. Measured source
coverage is **84%**. `compileall` passed for `src`, `tests`, and `scripts`.
JUnit and coverage XML are retained as `phase0_junit.xml` and
`phase0_coverage.xml`.

The standard pytest temporary directory was inaccessible under the managed
workspace policy. This was resolved reproducibly by configuring
`--basetemp=.pytest_tmp`; the directory is ignored by Git. No test was skipped
or weakened. A newly added logging test exposed multi-element NumPy array
serialization incorrectly attempting `.item()` before `.tolist()`; the logging
and hashing serializers were both corrected and regression-tested.

Static production-file scans found no local absolute path, old package import,
or prior repository reference. The environment has no `PYTHONPATH` override.
Only this repository is installed editable. `git grep` is rerun after the
report commit so untracked-file false negatives cannot occur.

## Failed or incomplete items

No Phase 0 acceptance item remains failed. Physical models, estimators,
controllers, and research performance results are intentionally not claimed in
this phase.

## Numerical issues

No physical simulation or controller numerical issue is applicable yet. The
three configured convex solvers passed the readiness probe. Solver availability
does not itself guarantee that later full-horizon MPC problems meet the 0.20 s
target; Phase 5 must measure and retain actual timing and failure data.

## Reproduction commands

```powershell
conda env update --name topo_sfr --file environment.yml
conda run -n topo_sfr python -m pip install -e .
conda run -n topo_sfr python scripts/00_export_environment.py
conda run -n topo_sfr python -m pytest -q
```

## Phase 1 entry decision

The Phase 0 gate is open. Phase 1 may implement the grid-frequency equations,
hidden-mode IBR truth dynamics, RK4/ZOH hybrid simulator, disturbances, mode
schedules, and simulator/controller information boundary. Phase 1 is not
accepted until equilibrium, sign, deadband, saturation, ramp, delay, mode
separation, and RK4/ZOH tests pass and `progress/PHASE_1_REPORT.md` is written.

