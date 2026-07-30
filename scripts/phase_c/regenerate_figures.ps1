$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& python scripts/phase_c/c3_validate_numerics.py
& python scripts/phase_c/c4_materiality.py --statistics-only
& python scripts/phase_c/c8_reporting.py
