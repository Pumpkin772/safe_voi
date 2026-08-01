$ErrorActionPreference = "Stop"
$packageRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sourceRoot = Join-Path $packageRoot "06_SOURCE"
$env:PYTHONPATH = (Join-Path $sourceRoot "src")

python (Join-Path $packageRoot "15_REPRODUCIBILITY\verify_manifest.py")
python (Join-Path $packageRoot "15_REPRODUCIBILITY\reproduce_minimal.py")

Write-Host "Full experiment replay stopped at the registered G5 certificate Gate."
Write-Host "F6-F8 and final seeds are intentionally NOT_EVALUATED."

