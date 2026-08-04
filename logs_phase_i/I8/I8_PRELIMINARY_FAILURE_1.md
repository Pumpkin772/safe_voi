# I8 preliminary reporting failure 1

- Classification: `CODE / OPTIONAL_DEPENDENCY_ASSUMPTION`
- Command: `python scripts/phase_i/run_i8_finalize.py`
- Failure: pandas `DataFrame.to_markdown()` attempted to import the optional
  `tabulate` package, which is not part of the locked `topo_sfr` environment.
- Scientific evidence affected: no.
- I6 configuration, results, thresholds, scenarios, seeds affected: no.
- Repair: replaced `to_markdown()` with a local deterministic Markdown-table
  renderer; no package installation or environment change was made.
- Verification: the repaired preliminary finalizer exited zero and the complete
  Phase-I test suite reported `42 passed`.

The failed attempt is retained and is not represented as a scientific or method
failure.
