# Direction5 VOI boundary final archive record

This record freezes the completed Direction5 selective VOI-ACCR-MPC study
before any successor work changes models or scenarios.

## Frozen scientific conclusion

```text
PAPER_READY_NO_PROBE_BOUNDARY
```

Within the registered finite capability, probe, controller, objective, and
Plant-A/Plant-B evaluation domain, all 1,920 evaluated points are in the
zero-value region.  The selected probe is `NONE`.  This is a bounded negative
result and must not be overwritten or reinterpreted by successor development.

## Frozen evidence

- scientific commit containing the final source and evidence:
  `0495abafdce6a9a2edfa9ce5a736c229f9e22fa8`;
- review package:
  `DIRECTION5_VOI_BOUNDARY_SINGLE_REVIEW_PACKAGE.zip`;
- package bytes: `16517339`;
- package SHA256:
  `7f89bec8a69c74d9cafd1e8338f25a9277101aed9ac10c8cad70aea601285c41`;
- development/validation/final boundary points: `1536 / 128 / 128 / 128`;
- positive/zero-value points: `0 / 1920`;
- corrected nonlinear Plant A: `40/40` physical successes;
- native ANDES Plant B: `12/12` physical successes;
- genuine normal1h profiles: `6/6` physical successes;
- recorded completed optimization calls: `56949`;
- recorded solver failures/fallbacks: `0 / 0`.

The ZIP is an untracked delivery artifact by repository policy.  Its identity
is fixed by the byte count and SHA256 above; the complete tracked scientific
source, statistics, manuscript, and replay workflow are in Git.

## Successor-work rule

Any successor study may change its model, scenario distribution, probe family,
or controller only in a separate directory and branch with a new preregistered
development/validation/final split.  It must cite this result as historical
evidence, preserve all new negative results, and must not replace the frozen
files or claim that a development-only positive cell is confirmatory evidence.
