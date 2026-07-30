# Phase C Repair Ledger

## C0-R1 — Baseline verification harness syntax

- Failure class: code.
- Evidence: the initial PowerShell index-verification command used an ambiguous variable followed by `:` and failed before reading or changing project evidence.
- Repair: delimited the interpolated variables explicitly and reran the same hash/size checks.
- Scientific standards changed: no.
- Result: all 20 launch-package entries matched `PACKAGE_INDEX.json` exactly.

## C1-R1 — Crossref partial publication date

- Failure class: data/metadata parser code.
- Evidence: one exact-DOI Crossref record supplied a `published.date-parts` year value of null, causing the first verification pass to stop before writing any literature output.
- Repair: use the first non-null year from `published`, `issued`, `published-online`, or `published-print`, with the Crossref creation year only as an explicitly recorded final metadata fallback.
- Scientific standards changed: no; exact DOI and title-fragment matching remain mandatory.
- Rerun result: parser advanced to exact DOI/title validation, which correctly rejected one miscited CDC DOI.

## C1-R2 — Seed citation DOI correction

- Failure class: metadata/reference.
- Evidence: exact DOI lookup showed `10.1109/CDC40024.2019.9029462` belongs to an unrelated Lyapunov-exponent paper.
- Repair: an independent Crossref title query identified and verified `10.1109/CDC40024.2019.9029522` for “Data-Enabled Predictive Control for Grid-Connected Power Converters.”
- Scientific standards changed: no; the mismatching entry was rejected rather than retained.
- Rerun result: exact matching advanced and rejected a second unrelated DOI before any output was accepted.

## C1-R3 — Koopman-MPC DOI correction

- Failure class: metadata/reference.
- Evidence: `10.1016/j.automatica.2018.08.011` resolved to a change-point detection paper, not the intended Korda–Mezić work.
- Repair: verified the intended paper and replaced the DOI with `10.1016/j.automatica.2018.03.046`.
- Scientific standards changed: no.
- Rerun result: all exact-DOI records passed; the run then stopped on the first official NERC URL because Conda Python could not build its TLS chain.

## C1-R4 — Official-source TLS trust chain

- Failure class: environment/network verification.
- Evidence: `urllib` raised `CERTIFICATE_VERIFY_FAILED` for an official NERC HTTPS document after all DOI metadata had validated.
- Repair: use the maintained `certifi` CA bundle when present, retaining full certificate verification; do not use an unverified SSL context.
- Scientific standards changed: no.
- Rerun result: all 50 records passed; 45 exact-DOI records and five official/preprint URLs were verified, with zero fabricated records.

## C2-R1 — ANDES packaged self-test entry

- Failure class: external-tool packaging.
- Evidence: `python -m andes selftest -q` attempted discovery in `site-packages/tests`, which the 2.0.0 wheel does not contain, and raised `ImportError`.
- Repair: do not weaken validation or fabricate the missing upstream suite. Run the bundled unmodified Kundur case through native ANDES power flow and TDS, and validate the project adapter with project-owned unit tests.
- Scientific standards changed: no; the missing upstream tests remain disclosed.
- Rerun result: Kundur PFlow and 2 s TDS both succeeded; all five C2 project tests passed.

## C3-R1 — Plant B slack-bus imbalance sign

- Failure class: physical model/sign.
- Evidence: the first C3 cross-model run produced negative Plant A but positive Plant B COI response to a positive area-1 load step. The network solve removed the injection mean and the rotor equation then interpreted reference-bus balance as free generation.
- Repair: retain the six-bus algebraic solve for inter-area exchange, explicitly allocate regional load plus signed tie-line exchange across the two machines in each area, and retain intra-area synchronizing torque.
- Scientific standards changed: no; the required sign/trend comparison caught the error before materiality experiments.
- Rerun result: both Plant A and Plant B COI frequency moved negative after a positive load step; eight combined C2/C3 tests passed.
