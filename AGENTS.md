# Repository instructions for coding agents

## Current binding authority: Direction5 VOI-ACCR-MPC result-driven study

The project name is **Direction5 / DIRECTION5 / direction5**.  The current
governing Goal is
`research/direction5_voi_accr_mpc_result_driven/CODEX_GOAL.md`; its only method
is **VOI-ACCR-MPC** (Value-of-Information Active Capability Certification and
Recourse MPC).  The full files in that research directory are the authority for
the current M1 -> M2 -> Final execution.

M1 has passed using the locked prototype in
`configs/direction5_voi_accr/m1_selected_lock.yaml`.  The selected development
result is documented in
`research/direction5_voi_accr_mpc_result_driven/M1_SELECTED_PROTOTYPE.md`.
It is not independent validation and does not authorize a paper claim.  The
next work is independent M2 validation with the frozen M1 configuration,
followed only on the registered path by Final, normal1h, manuscript, and the
single review package.  Preserve every unsuccessful development run.

The controller must probe around the current contract-MPC allocation only when
causal decision relevance and net-VoI Gates are positive; absence of a
certificate is not a trigger.  It must reduce to contract MPC in abstention
regions.  Ordinary controllers cannot read true capability, true load, future
events, or future modes.  Run one guarded simulation at a time with the
registered system-commit, private-memory, and descendant-process limits.

## Historical authority: Direction5 Phase I (superseded by the current Goal)

The project name is **Direction5 / DIRECTION5 / direction5**. The completed
governing Goal is `research/direction5_phase_i_final_convergence/CODEX_GOAL.md`;
its method is **DCSV-MPC** (Disturbance--Capability-Separated Viability MPC).
Read the following before changing current scientific code or claims:

1. `research/direction5_phase_i_final_convergence/CODEX_GOAL.md`
2. `research/direction5_phase_i_final_convergence/01_MASTER_EXECUTION_PLAN.md`
3. `research/direction5_phase_i_final_convergence/07_GATES_FAILURE_AUTO_REPAIR.md`
4. `research/direction5_phase_i_final_convergence/09_FINAL_REVIEW_PACKAGE_SPEC.md`
5. `results_phase_i/final/FINAL_STATUS.json`
6. `results_phase_i/final/ALL_GATES.csv`
7. `results_phase_i/final/FAILURE_LEDGER.csv`

Binding research status:

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

Gate state is I0--I5 `PASS`, I6 `FAIL`, I7 `NOT_EVALUATED`, and I8 `PASS`.
Phase H H7 is withdrawn as method evidence. I6 used 120 full nonlinear Plant-A
paired scenarios, 24 native ANDES Plant-B paired scenarios, and 12 genuine
3600 s normal-profile method runs. It failed the registered performance,
unresolved mathematical-infeasibility, fallback, and positive cross-plant
direction Gates. H5 is `NOT_SUPPORTED`; H1--H4 and H6 retain their explicitly
bounded statuses. Final seeds 100--159 were not consumed.

The active implementation is `src/direction5freq/`, `scripts/phase_i/`, and
`tests/phase_i/`. Namespaces `src/direction5_freq/` and `src/direction1freq/`
are retained solely to replay historical I0 evidence. Do not tune from I6,
run I7 final seeds, create Phase J/K, replace DCSV-MPC, or turn the negative
result into an affirmative performance claim. The only reviewed delivery name
is `DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE.zip`.

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

## Historical Phase-F state (superseded by the authority above)

The following records the older Direction1 Phase-F state and is retained as
historical evidence. It is not current runtime or claim authority. Its method
was:

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

## Progress snapshot (recorded 2026-08-02)

- Current branch: `direction1-phase-f-cdsr-mpc`.
- Latest scientific/evidence commit: `d424557f6cd8faf4b703c050b4031c7489281625`.
- Phase F execution is complete through its registered stopping path:
  F0--F4 completed and passed, F5 completed and failed its fatal certificate
  Gate, F6--F8 were deliberately recorded as `NOT_EVALUATED`, and F9 produced
  and independently replayed the negative review package.
- Active implementation: `src/direction1freq/`, `scripts/phase_f/`, and
  `tests/phase_f/`. The older `src/d5freq/` namespace and earlier phase scripts
  remain historical evidence.
- Best deployable baseline retained by the corrected analysis:
  `fixed_allocation_pi`.
- Phase-F test reference: 24 passed, 1 retained solver-accuracy warning.
- Full historical test reference: 709 passed, 2 known stale historical
  assertions failed, 3 warnings.
- No final seed was consumed, no failed episode was deleted, and no known/OOD
  result was generated after G5.
- The scientific baseline may be followed by documentation-only commits (for
  example portability/history updates). Such commits do not change the frozen
  evidence commit or the review ZIP recorded below.

### Phase-F stage ledger

| Stage | Commit | Result | What was established |
| --- | --- | --- | --- |
| F0 | `edea750` | PASS | Froze Phase E, reproduced the proposed-vs-applied action-history defect, showed that the old 1.846% bucket could not distinguish mathematical from numerical failure, and reproduced the old ZIP root-mapping replay defect. |
| F1 | `170391c` | PASS | Rebuilt the frozen selection/validation split and failure-aware statistics; H1 became supported, while H2/H3 were limited to the tested passive estimators and tested active probe. |
| F2 | `c33c522` | PASS | Added propose/select/commit action transactions and separate mathematical, numerical, terminal-reject, restoration, and fallback outcomes. Across 9,180 replay cycles, stored action-history mismatch was zero. |
| F3 | `b5707d3` | PASS | Locked guaranteed capability, explicit five-vertex delay, cumulative-energy, and residual sets. The dense delay hull was not claimed exact; an explicit state remainder was retained. |
| F4 | `13a9994` | PASS | Implemented genuine rolling common-sequence CDSR-MPC, lexicographic feasibility restoration, transactional supervision, and SG-backup routing. Forced restoration and backup paths were tested separately. |
| F5 | `8caa160` | FAIL/FATAL | Independently recomputed robust reachable sets for two stable SG backup designs at 2 s and 4 s. All tested sets violated registered admissibility limits, so only a finite-horizon certificate remained. |
| F6 | n/a | NOT_EVALUATED | Validation was skipped by the registered G5 stop; no result was imputed. |
| F7 | n/a | NOT_EVALUATED | Final lock/final seeds were not entered. |
| F8 | n/a | NOT_EVALUATED | Plant-A/Plant-B known/OOD comparative evidence was not run. |
| F9 | `d424557` | PASS | Sealed the negative result and built a strict, sub-512 MB review ZIP with manifest, CRC, license exclusion, and fresh extracted replay checks. |

## Chronological research history and claim lineage

The repository deliberately retains superseded conclusions. Always distinguish
an outcome that was valid under an old protocol from a claim that remains valid
after later audits.

### Phase A / original D5 SD-BMPC build

- Phase 0 established the independent package and reproducible baseline.
- Phase 1 implemented physical models and the hybrid simulator.
- Phase 2 added estimation and baseline control.
- Phase 3 implemented unlabeled mode discovery.
- Phase 4 added online belief/OOD diagnosis.
- Phase 5 implemented and gated the self-diagnosing belief MPC.
- Phase 6 added experiment, audit, and review infrastructure. The frozen Phase-6
  commit was `20f652f5f8b180a2518798d0ed85aa3f48212908`.
- Previously uncommitted Phase-7 review changes were consolidated into
  `f8038467bc7a99b519f6bec692a9ad9c06f8cd19`, tagged
  `phase-a-final-reviewed-v2`.
- This line is retained as historical SD-BMPC evidence; it is not the current
  Direction1 method.

### Phase B1 / scientific bottleneck audit

- Added the evaluation-only B5 simulator-exact nonlinear Oracle and audited SG
  capability value, exact-vs-ARX mismatch, passive identifiability, load/mode
  confounding, sticky prior, worst-mode cost, tightening, and binary fallback.
- The contemporaneous result at
  `9e003ba975a1f40fc969a360a4f390ec9cbcc105` was
  `COMBINED:CONTROL_DESIGN_DOMINANT+MODEL_MISMATCH_DOMINANT`.
- Phase B2 later found that all preregistered triggers were false and that the
  old analysis forced a dominant label, used a distorted mean episode-wise
  relative ratio, excluded scientific failures, over-relied on SG mileage, and
  overstated B5. The corrected B1 conclusion is therefore
  `INCONCLUSIVE_NO_DOMINANT_BOTTLENECK`; the original combined label is only
  historical output.

### Phase B2 / scientific hardening

- Reanalysed Phase-B1 data, built corrected two-area ACE/tie-line models,
  physical Plant B, O0--O3 Oracle layers, multiple-shooting NMPC, and a
  success-first balanced protocol.
- It stopped at `PROBLEM_NOT_MATERIAL` and was frozen at
  `5953ffcf71a641581364e0684b982852def4421c`, later tagged
  `direction5-phase-b2-reviewed-invalidated`.
- Phase C withdrew `PROBLEM_NOT_MATERIAL`: corrected physical scaling and a
  fair rolling current-capability Oracle showed materiality on both plants.
  Treat the Phase-B2 conclusion as invalidated historical evidence.

### Phase C / full physical rebuild and method completion

- Corrected frequency units, inertia/damping, BESS energy, and shared capability;
  rebuilt Plant A and a native multi-machine RMS/DAE Plant B; qualified a fair
  rolling Oracle; compared detection and control-critical time; and selected
  C6-A set-adaptive MPC.
- Materiality passed on both plants, while the locked final method failed to
  beat the strongest deployable robust-capability-set MPC, especially OOD. The
  contemporaneous status was `METHOD_NOT_SUPPORTED_BY_EVIDENCE`.
- Phase D then invalidated the C5 passive-identifiable and C6/C8 paper claims
  because Plant-B BESS power did not enter native machine balance, centered and
  future-window processing was noncausal, algebraic allocation was called MPC,
  and final scenario factors were confounded.
- Frozen historical tag/commit:
  `direction5-phase-c-reviewed-invalidated` at
  `86f982baeda32ee62f8a6117bfe66bc3a9e9bdbb`.

### Phase D / Direction1 CRCS-TMPC attempt

- Renamed the project Direction1, rebuilt physical/native plant interfaces,
  repaired causality requirements, required genuine rolling MPC, and planned
  the unique CRCS-TMPC method.
- The registered passive capability-set H2 Gate failed after 120 D3 validation
  episodes (55 failed), so CRCS-TMPC and all final known/OOD experiments were
  not implemented/evaluated. The old status was
  `PASSIVE_CAPABILITY_SET_NOT_SUPPORTED`.
- Phase E independently reproduced decisive defects: the nominal PI loop
  self-excited, delay-set changes were omitted by alarm-only update-time scoring,
  control-loss time was not a matched physical counterfactual, all-failed
  candidate logic selected the last candidate, and H2 was tested before H1.
  Therefore the binding interpretation is
  `PHASE_D_GATE_INVALIDATED_BY_CLOSED_LOOP_AND_EVALUATION_DEFECTS`, not passive
  impossibility.
- Frozen tag/commit: `direction1-phase-d-negative-reviewed` at
  `11f0379e0e7bd9b1ddf97be8d88b7f918bbb52e9`.

### Phase E / science recovery and capability control

- Repaired the nominal 2/4 s SFR loop, update-time and control-loss definitions,
  candidate selection, physical Plant A, and native ANDES Plant B.
- A fair rolling current-capability NMPC Oracle supported H1 materiality.
  Registered passive identification failed; the registered active probe was
  unsafe; branch R (Capability-Set Robust Tube MPC) was selected.
- E6 stopped fatally because the recorded rolling-QP failure bucket was 1.846%,
  over the 1% Gate. Known/OOD and final seeds remained not evaluated. The
  contemporaneous status was `METHOD_NOT_SUPPORTED_BY_EVIDENCE`.
- Phase F0 showed that the old controller committed proposed rather than applied
  actions and that the saved failure fields could not classify mathematical vs
  numerical failure. It also found a package-relative replay defect. The Phase-E
  claim is therefore narrowed to
  `METHOD_IMPLEMENTATION_AND_CERTIFICATE_INCOMPLETE`, not failure of the whole
  method class.
- Frozen tag/commit: `direction1-phase-e-reviewed` at
  `8fd7d4515377996cd9e17809ecd045a835d2916d`.

### Phase F / CDSR-MPC with feasibility restoration

- Kept the scientific question fixed and implemented only CDSR-MPC.
- Repaired transactional action history and solver taxonomy, corrected H1--H3,
  calibrated capability/delay/energy/residual sets, implemented true rolling
  robust prediction with one common control sequence, and added feasibility
  restoration plus SG terminal-backup routing.
- F5 could not produce an admissible nonempty robust backup set for either
  tested backup design. The project therefore stopped before validation/final
  experiments and produced a complete negative package.
- Current binding status: `NO_NONEMPTY_ROBUST_BACKUP_SET`; certificate:
  `FINITE_HORIZON_ONLY`; recursive feasibility and robust switching safety:
  not certified.

## Review-package lineage

These ZIPs are intentionally untracked delivery artifacts. Hash them after a
folder transfer; a Git-only clone will not contain them.

| Phase | Review ZIP | Bytes | SHA256 |
| --- | --- | ---: | --- |
| A v2 | `D5_FROM_SCRATCH_SD_BMPC_REVIEW_PACKAGE.zip` | 16,491,773 | `2e1c3bfc380c57172a5d96663a6ab90cf95b79511f60cefce73ce4c38e2f04a9` |
| B1 | `D5_PHASE_B1_BOTTLENECK_AUDIT_REVIEW_PACKAGE.zip` | 82,820,975 | `aeb032be1e4a4f06fc317491064f5fd279c590d00a8cc48c035504704c883f3f` |
| B2 | `D5_PHASE_B2_SCIENTIFIC_HARDENING_REVIEW_PACKAGE.zip` | 7,281,425 | `5280a39e97a99f0bd831d0d5d2f72c7faae6b04b45e5e8fcf5b644325c9b1ebe` |
| C | `DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip` | 2,168,723 | `28f64c4668a86c4d336619f27382c16766a0b425a6cd6895fd816f07aff809e9` |
| D | `DIRECTION1_PHASE_D_CRCS_TUBE_MPC_SINGLE_REVIEW_PACKAGE.zip` | 3,648,745 | `ed471534e162d5748cb8d735d9ca1f017ac6ad2c7ab9c125c6351e6ef658ebc6` |
| E | `DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip` | 17,446,090 | `d30be15f1d1a4c0a80339ff3408a50397adc1e98e85a4e673a5b2b7c66b61d9c` |
| F | `DIRECTION1_PHASE_F_CDSR_MPC_SINGLE_REVIEW_PACKAGE.zip` | 11,869,956 | `675f8982f20b0ffe73a03488e0859da1e45d309e2fe54e7e49a8a7354e1a7544` |

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

Do not hard-code an interpreter under a specific drive or user directory. If
activation is unavailable in the calling shell, use
`conda run -n topo_sfr python ...`.

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
