$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& python scripts/phase_d/reproduce_minimal.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
