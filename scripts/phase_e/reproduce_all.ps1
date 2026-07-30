$ErrorActionPreference = "Stop"
$python = "D:\Miniconda3\envs\topo_sfr\python.exe"
& $python -m scripts.phase_e.run_e0_forensic
& $python -m scripts.phase_e.run_e1_literature
& $python -m scripts.phase_e.run_e2_rebuild
& $python -m scripts.phase_e.run_e3_materiality --workers 4
& $python -m scripts.phase_e.reanalyze_e3_full
& $python -m scripts.phase_e.run_e4_passive_identifiability
& $python -m scripts.phase_e.run_e5_active_feasibility
& $python -m scripts.phase_e.reanalyze_e5
& $python -m scripts.phase_e.run_e6_selected_method --workers 4
if ($LASTEXITCODE -ne 2) { throw "E6 must terminate with the retained fatal Gate (exit 2)." }
& $python -m scripts.phase_e.e9_finalize_negative
& $python -m pytest tests/phase_e -q
