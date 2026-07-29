# Reproducibility Commands

Run from the repository root with `MOSEKLM_LICENSE_FILE=D:\Backup\Downloads\mosek.lic` and `GRB_LICENSE_FILE=D:\Backup\Downloads\gurobi.lic`.

```powershell
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python scripts/phase_b1_01_validate_oracle.py
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python scripts/phase_b1_02_run_materiality_audit.py
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python scripts/phase_b1_03_run_model_audit.py
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python scripts/phase_b1_04_run_identifiability_audit.py
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python scripts/phase_b1_05_run_control_design_audit.py
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python scripts/phase_b1_06_make_decision.py
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python -m pytest
D:\Miniconda3\condabin\conda.bat run -n topo_sfr python -m pytest tests_phase_b1
```
