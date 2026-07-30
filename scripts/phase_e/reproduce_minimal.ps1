$ErrorActionPreference = "Stop"
$python = "D:\Miniconda3\envs\topo_sfr\python.exe"
& $python -m scripts.phase_e.reproduce_minimal
& $python -m pytest tests/phase_e -q
