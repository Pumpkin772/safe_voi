# How to review

1. Verify package SHA256 and `13_GIT_AND_MANIFEST/FILE_MANIFEST.csv`.
2. Confirm C0–C8 decisions in `01_SCIENCE/SCIENCE_GATE_DECISIONS.json` and `progress/decision_ledger.md`.
3. Review units/energy/native-model boundary in `03_MODEL_AND_THEORY` and `06_TESTS_AND_VERIFICATION`.
4. Recompute C4/C5/C8 summaries from Parquet in `08_RAW_RESULTS` using the included scripts.
5. Confirm all 1280 C8 statuses, including failures and O3 `not_evaluated`, remain present.
6. Reproduce with `12_REPRODUCIBILITY/RUN_ALL.md`.
