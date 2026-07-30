# Phase B2-0/1 — Baseline Freeze and Corrected Phase-B1 Audit

## Frozen input

- Phase-B1 commit: `9e003ba975a1f40fc969a360a4f390ec9cbcc105`
- Phase-B1 review ZIP SHA256: `aeb032be1e4a4f06fc317491064f5fd279c590d00a8cc48c035504704c883f3f`
- Frozen files: 15,856
- Frozen bytes: 489,656,248
- Baseline manifest SHA256: `6c3deed033b7ff37aa2d0d57a901cc3a7a67a7d567ce4f73115cd2f29e12df88`

The manifest was verified after the corrected analysis. No file below the
Phase-B1 artifact, result, figure, log, or progress roots changed.

## Corrected analysis boundary

The correction read the existing Phase-B1 CSV tables only. It read 15,120
per-episode rows and reran zero episodes. The main estimators are paired,
scenario-balanced differences and ratios of scenario-balanced means. The old
episode-wise relative-ratio mean is retained only as a diagnostic column.

All pairing is outer pairing with explicit both-success, method-only failure,
reference-only failure, and both-failure outcomes. In particular, the 60 B0
scientific failures at SG-C remain in the primary success-first evidence.

Total resource cost contains SG energy, IBR energy, SG mileage, and IBR
mileage. The registered IBR-to-SG cost ratios are 0.25, 0.5, 1.0, and 2.0.

## Corrected Phase-B1 result

`INCONCLUSIVE_NO_DOMINANT_BOTTLENECK`

- Active triggers: none.
- Corrected B4-vs-B5 overall scenario/SG-balanced frequency-IAE effect:
  `-1.98%` (B4 minus B5), versus the distorted old episode-ratio mean of
  `+8.13%`.
- Evaluation-only Bayes delayed/censored fraction: `36.55%`, below the frozen
  `50%` identifiability trigger.
- The apparent no-sticky gain is ineligible under success-first because it has
  four method-only scientific failures while P_old has none.
- B5 is classified as an exact-plant, finite-action, constant-shooting
  benchmark. It is not an exact optimal or globally optimal Oracle.

Corrected B1 materiality has candidate evidence at low IBR-cost assumptions,
but B5 is not a credible optimal ceiling. Therefore the evidence cannot support
either a dominant bottleneck or a definitive problem-not-material claim.

## Regression gates

- Phase-B2 corrected-statistics tests: 8 passed.
- Legacy repository tests: 609 passed, 2 existing solver warnings.
- Decision regression: all-false triggers return INCONCLUSIVE; COMBINED uses
  active triggers only.
