# Reproducibility Commands

Run from the repository root with the `topo_sfr` Conda environment. On Windows, set `MOSEKLM_LICENSE_FILE` only for legacy tests; the final path itself is not packaged.

```powershell
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_00_freeze_baseline.py
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_01_correct_phase_b1.py
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_02_validate_plant_b.py
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_03_fit_identified_oracles.py
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_04_validate_oracle_hierarchy.py
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_05_control_relevant_identifiability.py
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_06_run_final_experiment.py --mode validation
# Final seeds are locked and must not be rerun for tuning:
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_06_run_final_experiment.py --mode final
D:\Miniconda3\envs	opo_sfr\python.exe scripts\phase_b2_07_finalize_analysis.py
```

The review package includes exact resolved configs, environment inventory, solver versions, test logs, Git state, hashes and the final-run manifest.
