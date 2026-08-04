# Direction5 Phase I: final scientific convergence

This repository's current project is **Direction5 / DIRECTION5 / direction5**.
The sole active method is **DCSV-MPC** (Disturbance--Capability-Separated
Viability MPC), governed by
`research/direction5_phase_i_final_convergence/CODEX_GOAL.md`.

## Binding outcome

```text
DIRECTION5_TERMINATED_WITH_DECISIVE_NEGATIVE_EVIDENCE
```

I0--I5 passed. Corrected full validation at I6 failed four registered Gates:
none of the three core metrics achieved at least 8% improvement with a positive
cluster-bootstrap lower bound; unresolved mathematical infeasibility exceeded
0.1%; fallback exceeded 1%; and Plant A/B did not show a positive performance
direction. I7 final seeds were therefore not evaluated, and no success/failure
was imputed to them. I8 sealed and independently replayed the negative result.

The result is bounded rather than category-level: Phase I retains the
actual-POI load observer, causal power/ramp/delay deliverability estimator,
contract-floor semantics, conditional local Plant-A RPI sets, finite-horizon
bridge certificates, and physical-infeasibility certificates. It does not
support DCSV-MPC deployment advantage, global recursive feasibility, or a
rigorous native Plant-B RPI claim.

## Active source and evidence

- Active source: `src/direction5freq/`
- Phase scripts: `scripts/phase_i/`
- Tests: `tests/phase_i/`
- Locked validation: `configs/phase_i/i6_validation_lock.yaml`
- Final status: `results_phase_i/final/FINAL_STATUS.json`
- Final reports: `research_outputs_phase_i/08_FINAL/`
- Final figures: `figures_phase_i/I8/`

Older Direction1, `direction5_freq`, and `d5freq` materials remain immutable
historical evidence. They are not the active method or current claim authority.

## Environment and verification

Use the repository-owned Python 3.11 environment:

```powershell
conda env update --name topo_sfr --file environment.yml --prune
conda activate topo_sfr
python -m pip install -e . --no-deps
python -m pytest tests/phase_i -q
```

The reviewed delivery is:

```text
DIRECTION5_PHASE_I_FINAL_CONVERGENCE_SINGLE_REVIEW_PACKAGE.zip
```

After extraction, run from the package root:

```powershell
python 15_REPRODUCIBILITY/verify_manifest.py
python 15_REPRODUCIBILITY/reproduce_minimal.py
```

No commercial solver license is included or required by the Phase-I replay.
