# I8 test failure 1

- Result: `41 passed, 1 failed`.
- Failed test: `test_final_review_sections_and_builder_names_are_locked`.
- Cause: the test searched the builder source for literal strings
  `"00_README"` and `"17_FINAL_STATUS"`, while the builder intentionally
  constructs all 18 names from an enumerated tuple.
- Repair: import and assert the computed `DIRECTORIES` constant directly.
- Scientific code or standards changed: no.
- Re-run: `42 passed`.

This failed test result remains part of the audit trail.
