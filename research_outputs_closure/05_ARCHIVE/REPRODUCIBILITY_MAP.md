# Reproducibility map

1. From the extracted package root, run `python 16_REPRODUCIBILITY/verify_manifest.py`.
2. Run `python 16_REPRODUCIBILITY/reproduce_minimal.py` for a standard-library replay of final state, C0 audit facts, validation/confirmation Gates, seed consumption, and solver identities.
3. Install `09_SOURCE_ENV/repository/environment.yml`, then run the test commands in `10_TESTS/TEST_COMMANDS.md`.
4. Full validation and confirmation entry points, locked manifests, source, and raw outputs are retained. Final seeds are already consumed; do not rerun the confirmatory protocol as a new scientific sample or tune from it.
5. Figures can be regenerated with `09_SOURCE_ENV/repository/scripts/direction5_closure/run_c4_figures.py` after installing the environment.
