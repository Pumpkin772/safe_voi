# Repository instructions for coding agents

## Scope and path portability

This file applies to the entire repository.

- Always discover the repository root with `git rev-parse --show-toplevel` and
  run commands from that directory. Never assume a Windows user name, drive
  letter, Desktop location, Conda installation path, or license path.
- The repository may live below a path containing spaces or non-ASCII
  characters. In PowerShell, quote paths and prefer `-LiteralPath`.
- Treat absolute paths found in historical logs, XML files, frozen reports, or
  old reproduction notes as recorded evidence from an earlier computer. Do not
  use them as runtime configuration and do not rewrite historical evidence just
  to make the paths look current.
- Preserve the `.git` directory when moving the folder. A Git clone contains
  tracked source and evidence, but it does not contain the untracked review ZIPs,
  staged review-package directories, or their sidecars; transfer those files
  separately when the reviewed artifact itself is required.
- Never run `git clean`, delete generated evidence, or reset user changes merely
  to obtain a clean status. Inspect `git status --short` first and preserve all
  unrelated tracked and untracked files.

Portable PowerShell initialization:

```powershell
$repoRoot = (git rev-parse --show-toplevel).Trim()
Set-Location -LiteralPath $repoRoot
git status --short
```

If Windows path-length errors occur, move the repository under a shorter parent
directory. `git config --local core.longpaths true` may be used if needed; do
not rename scientific files or flatten the repository tree.

## Current authoritative project state

The project name is **Direction1 / DIRECTION1**. The latest completed scientific
phase is Phase F, whose only method is:

```text
CDSR-MPC
Capability-and-Delay-Set Robust MPC with Feasibility Restoration
```

Read these before changing scientific code or claims:

1. `research/direction1_phase_f_cdsr_mpc/CODEX_GOAL.md`
2. `research/direction1_phase_f_cdsr_mpc/08_GATES_FAILURE_AUTO_REPAIR.md`
3. `research/direction1_phase_f_cdsr_mpc/09_FINAL_REVIEW_PACKAGE_SPEC.md`
4. `research_outputs_phase_f/final/FINAL_STATUS.json`
5. `results_phase_f/F9/ALL_GATES.csv`
6. `results_phase_f/F9/FAILURE_LEDGER.csv`

The root `README.md` still describes the frozen Phase-D state and is not the
authority for the current Phase-F result.

The frozen Phase-F scientific baseline is commit
`d424557f6cd8faf4b703c050b4031c7489281625`. Its binding result is:

```text
NO_NONEMPTY_ROBUST_BACKUP_SET
```

Gate state:

- G0--G4: `PASS`
- G5: `FAIL`
- G6--G8: `NOT_EVALUATED`
- G9: `PASS` only in the verified review package/post-package verification

G5 failed because neither of the two tested stable SG terminal-backup designs
produced an admissible nonempty robust backup set under the locked registered
uncertainty set. The valid certificate is `FINITE_HORIZON_ONLY`; recursive
feasibility and robust switching safety are not certified. Phase-F known/OOD,
Plant-B comparative evaluation, and final seeds were not run. Do not impute
`NOT_EVALUATED` as a failure.

This phase is stopped for review. Do not run F6--F8, consume final seeds, tune
from final evidence, substitute another controller, or broaden H2/H3 into
category-level impossibility claims unless the user provides a new explicit
governing Goal.

## Environment on a new computer

Use the repository-owned `environment.yml`; the required environment name is
`topo_sfr`, with Python 3.11. Install Conda/Miniforge anywhere convenient.

For a new environment:

```powershell
conda env create --file environment.yml
conda activate topo_sfr
python -m pip install -e . --no-deps
```

If `topo_sfr` already exists:

```powershell
conda env update --name topo_sfr --file environment.yml --prune
conda activate topo_sfr
python -m pip install -e . --no-deps
```

Do not hard-code an interpreter such as `D:\...\python.exe`. If activation is
unavailable in the calling shell, use `conda run -n topo_sfr python ...`.

Basic environment checks:

```powershell
python --version
python -m pip check
python -c "import direction1freq, andes, casadi, cvxpy; print(andes.__version__); print(cvxpy.installed_solvers())"
```

`environment.yml` is the dependency authority. Important pins include Python
3.11, ANDES 2.0.0, CasADi 3.7.2, IPOPT 3.14.19, and one OpenBLAS runtime on
Windows. Do not silently upgrade these while reproducing the frozen result.

## Commercial solver licenses

License files are local credentials and are intentionally excluded from Git and
review packages. They may be stored anywhere on the new computer. When a run
actually needs licensed solvers, set per-session paths without copying the files
into the repository:

```powershell
$env:GRB_LICENSE_FILE = (Resolve-Path -LiteralPath "<local-path>\gurobi.lic").Path
$env:MOSEKLM_LICENSE_FILE = (Resolve-Path -LiteralPath "<local-path>\mosek.lic").Path
```

Never print license contents, commit them, add them to a ZIP, or infer that the
old computer's license locations exist. Phase F uses OSQP and CLARABEL; licensed
solvers are mainly needed by portions of the historical full test suite.

## First validation after migration

Run the Phase-F suite first:

```powershell
python -m pytest tests/phase_f -q
```

Reference result at the frozen baseline: `24 passed`, with one retained CVXPY
solution-accuracy warning. A different result on a new computer is a migration
or dependency issue until diagnosed; do not change scientific thresholds to
make it pass.

The historical whole-repository reference is `709 passed, 2 failed, 3
warnings`. The two retained failures are old assertions that (1) Phase D must
have no Direction1 controller and (2) the current branch must remain Phase E.
They conflict with the deliberately completed Phase F and are not Phase-F
functional failures. Keep them visible rather than deleting or weakening them.

## Frozen review artifact

When the review ZIP was transferred with the folder, verify it before use:

```powershell
$zip = Join-Path $repoRoot "DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip"
Get-Item -LiteralPath $zip | Select-Object FullName, Length
Get-FileHash -LiteralPath $zip -Algorithm SHA256
Get-Content -LiteralPath "$zip.sha256"
```

Frozen reviewed artifact:

- file: `DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip`
- bytes: `11869956`
- SHA256: `675f8982f20b0ffe73a03488e0859da1e45d309e2fe54e7e49a8a7354e1a7544`
- scientific commit recorded inside the package: `d424557f6cd8faf4b703c050b4031c7489281625`

After extracting to any directory, run from the extracted package root:

```powershell
python 15_REPRODUCIBILITY/verify_manifest.py
python 15_REPRODUCIBILITY/reproduce_minimal.py
```

Expected minimal replay facts are: final status
`NO_NONEMPTY_ROBUST_BACKUP_SET`, certificate `FINITE_HORIZON_ONLY`, recomputed
backup-set nonempty `false`, final seeds consumed `false`, and known/OOD both
`NOT_EVALUATED`.

Do not rebuild the ZIP merely as a migration check: rebuilding records the new
HEAD/environment and produces a different artifact hash. If the frozen ZIP was
not transferred, report it as missing and decide explicitly whether to copy the
reviewed artifact or create a new reassembly.

## Scientific and implementation invariants

- Ordinary controllers must not read true capability/regime, hidden parameters,
  true load, future events, future modes, or final-seed information. Oracles are
  evaluation-only.
- The MPC transaction must commit the action actually applied after terminal
  rejection, restoration, or fallback; never commit an unexecuted proposal as
  the previous action.
- Keep mathematical infeasibility, numerical failure, terminal rejection,
  feasibility restoration, and fallback as separate auditable outcomes.
- Any object called MPC must solve a rolling finite-horizon optimization with a
  common control sequence over the registered capability/delay uncertainty set.
- Preserve shared PFR+SFR power/ramp limits, cumulative energy, headroom, SoC,
  efficiency, delay, and service availability constraints.
- Do not claim recursive feasibility or robust safety without a recomputable
  certificate covering the stated uncertainty set.
- Preserve every failed episode and every warning. Keep failures separate from
  `NOT_EVALUATED`; never tune on final seeds or relax preregistered Gates after
  seeing final evidence.
- Historical Phase B/C/D/E code and outputs are evidence, not the active method.
  Avoid modifying them unless a new Goal explicitly requires a historical
  correction.

## Editing and handoff discipline

- Inspect `git status --short`, the current branch, and the governing Goal before
  editing. Do not assume the checkout is clean.
- Use repository-relative paths in code, configs, docs, and commands. Derive
  output paths from `Path(__file__)`, the Git root, or an explicit CLI argument.
- Keep generated environments, caches, credentials, and licenses out of Git.
- Run focused tests for changed code. Run `tests/phase_f` when changing active
  Phase-F source or evidence. Report historical-suite failures separately.
- Before handoff, report changed files, tests, current commit/status, and whether
  any review-artifact hash changed.
