$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& python -m pytest
& python scripts/phase_c/run_master_pipeline.py --config configs/phase_c/master.yaml --resume --dry-run
Write-Host 'Final simulations are locked; inspect C7 manifest before an intentional rerun.'
