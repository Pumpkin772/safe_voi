$ErrorActionPreference = "Stop"
$python = "D:\Miniconda3\envs\topo_sfr\python.exe"
# Each experiment script regenerates its figure from deterministic registered data.
& $python -m scripts.phase_e.run_e2_rebuild
& $python -m scripts.phase_e.reanalyze_e3_full
& $python -m scripts.phase_e.run_e4_passive_identifiability
& $python -m scripts.phase_e.reanalyze_e5
# E6 figure source is the frozen paired-comparison CSV; rerun only if full replay is desired.
