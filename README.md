# DIRECTION1: CRCS-TMPC for black-box IBR capability changes

This repository is the Direction1 research implementation for control-relevant capability-set adaptive tube MPC (CRCS-TMPC) in multi-area frequency regulation. The governing contract is `research/direction1_phase_d_crcs_tube_mpc/CODEX_GOAL.md`.

The former D5/SD-BMPC and Phase C code under `src/d5freq` is retained only as historical evidence. It is not the active method namespace and its passive-identifiable or method-performance conclusions are invalidated for paper evidence. New Direction1 implementation lives under `src/direction1freq`.

## Binding Phase D result

Phase D stopped at its preregistered H2 Gate. Natural closed-loop public I/O did not maintain the required joint capability-set coverage or causal update timing after the initial estimator and two allowed development repairs. The research status is:

```text
PASSIVE_CAPABILITY_SET_NOT_SUPPORTED
```

Per the Goal, no Direction1 Oracle, CRCS-TMPC, active-identification substitute, or other controller was implemented after this fatal Gate. H1, H3, H4, the best baseline, and known/OOD controller outcomes are `not_evaluated`, not failures.

## Environment

Use the existing Python 3.11 Conda environment `topo_sfr`:

```powershell
conda env update --name topo_sfr --file environment.yml
conda activate topo_sfr
python -m pip install -e ".[dev,notebook,solvers]"
```

The completed negative path uses ANDES 2.0.0 for native Kundur Plant B validation and does not require commercial solver licenses. License files must never be committed or packaged.

## Reproduction

```powershell
powershell -ExecutionPolicy Bypass -File scripts/phase_d/reproduce_minimal.ps1
```

The full D2–D3 reproduction, figure regeneration, raw evidence, failure ledger, and Gate decisions are documented under `research_outputs_phase_d/`, `results_phase_d/`, `figures_phase_d/`, `logs_phase_d/`, and `progress_phase_d/`.

All failed episodes are retained. Planned post-H2 experiments are explicitly stored as `not_evaluated`; they are never counted as method failures.
