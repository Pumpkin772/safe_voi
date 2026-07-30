$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
& python scripts/phase_d/d2_validate_physics.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& python scripts/phase_d/d3_capability_gate.py
if ($LASTEXITCODE -ne 3) { throw 'D3 must terminate with the registered scientific Gate code 3.' }
& python scripts/phase_d/d7_lock_negative_protocol.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& python scripts/phase_d/d8_finalize_negative.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& python -m pytest tests/phase_d -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Reproduced binding result: PASSIVE_CAPABILITY_SET_NOT_SUPPORTED'
