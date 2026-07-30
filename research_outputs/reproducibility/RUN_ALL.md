# Reproduction

Use Python 3.11 in the locked `topo_sfr` environment. From repository root:

```powershell
pip install -e .
python -m pytest
python scripts/phase_c/run_master_pipeline.py --config configs/phase_c/master.yaml --resume --dry-run
```

`reproduce_minimal.ps1` reruns Phase C tests and statistical/figure generation without final simulation. `reproduce_all.ps1` verifies the complete test suite and stage contract. Final simulations are protected after the seed lock; an intentional rerun must use the unchanged C7 manifest and C8 runner.
