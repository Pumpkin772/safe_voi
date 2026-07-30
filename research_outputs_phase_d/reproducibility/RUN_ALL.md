# Reproducibility commands

Use the Conda environment `topo_sfr` defined by `environment.yml`. The environment used for the review run is at `D:\Miniconda3\envs\topo_sfr`, but scripts do not hard-code that location.

## Windows / PowerShell

Minimal verification (about 1 minute after dependencies are installed):

```powershell
conda activate topo_sfr
powershell -ExecutionPolicy Bypass -File scripts/phase_d/reproduce_minimal.ps1
```

Full D2–D3 reproduction (approximately 20–60 minutes on a four-core Windows workstation; ANDES initialization and D3 scenario simulation dominate):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/phase_d/reproduce_all.ps1
```

Rebuild figures only from retained raw evidence:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/phase_d/regenerate_figures.ps1
```

## Cross-platform

```bash
conda env create -f environment.yml
conda activate topo_sfr
python scripts/phase_d/reproduce_minimal.py
```

ANDES 2.0.0 and the bundled Kundur VSC case are required for the Plant B physics reproduction. No commercial solver license is required for the completed negative path because D4–D6 were not reached.
