# SD-BMPC: Hidden-Mode Frequency Control from Scratch

This repository is an independent implementation of **Self-Diagnosing
Belief-Space Model Predictive Frequency Control (SD-BMPC)** for a single-area
frequency system with a black-box inverter-based resource (IBR). It is built
from first principles and does not import, copy, or depend on prior paper
reproduction repositories.

The controller will infer an online probability distribution over externally
identified IBR modes, account for that uncertainty in a shared-input MPC, and
fall back to synchronous-generation LQI control when the model library is not
credible or the optimizer fails.

## Environment

The original project brief requested a new Python 3.11 Conda environment. The
user subsequently chose to reuse the existing environment named `topo_sfr`;
that decision is recorded in `environment.yml`. Synchronize that environment
with:

```powershell
conda env update --name topo_sfr --file environment.yml
conda activate topo_sfr
python -m pip install -e ".[dev,notebook,solvers]"
```

MOSEK is the preferred optimization backend and Gurobi is the fallback. Their
Python packages are listed, but valid local licenses remain the user's
responsibility and must never be committed or packaged.

## Phase 0 check

From the repository root:

```powershell
conda run -n topo_sfr python -m pytest -q
```

The package uses a `src` layout. Pytest is configured to include `src` during
development; installing the editable package is still recommended.

## Repository layout

- `configs/`: versioned physical, diagnosis, control, and experiment settings.
- `src/d5freq/`: implementation package.
- `tests/`: unit, integration, and numerical regression tests.
- `scripts/`: reproducible pipeline entry points.
- `artifacts/`: learned model libraries and calibration outputs.
- `results/`: saved episode data, summaries, and figures.
- `progress/`: phase acceptance reports.
- `research_docs/`: derivations, experiment notes, and limitations.

## Information boundary

True IBR modes are simulator-private. Mode schedules and OOD truth in the
configuration files are available only to simulation orchestration and the
evaluation merge step. A controller receives measurements, identified mode
models, belief/OOD diagnostics, and previous commands; it never receives true
mode names, truth indices, truth ordering, or an evaluation record. Oracle MPC
will be isolated as an evaluation-only upper bound.

Failed episodes, solver failures, timeouts, constraint violations, and OOD
misses are research results and must be retained.

## Phase status

Phase 0 establishes the repository, environment declaration, deterministic
configuration, output locations, and minimal import test. Later phases must
follow the acceptance gates in the supplied project specification; no result
claim is made by this scaffold.
