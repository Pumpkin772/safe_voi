# Phase B0 — Reviewed-v2 baseline freeze

## Outcome

Phase B0 is complete.  The second review package was authenticated, its
uncommitted Phase-7 patch was matched byte-for-byte against the working tree,
and that patch was converted into an explicit Phase-A baseline commit.  The
legacy evidence roots are now protected by a full per-file hash manifest.

## Review-package authentication

- Package: `D5_FROM_SCRATCH_SD_BMPC_REVIEW_PACKAGE.zip`
- Size: `16,491,773` bytes
- Required and observed SHA256:
  `2e1c3bfc380c57172a5d96663a6ab90cf95b79511f60cefce73ce4c38e2f04a9`
- Frozen Phase-6 commit embedded in the package:
  `20f652f5f8b180a2518798d0ed85aa3f48212908`
- Archived `git/diff.patch` SHA256:
  `b6b7c82b593d1b0247c74c040ba5b9e55dc4074d830670ee6d1ff46c0e36c832`
- The archived patch matched the pre-commit local tracked diff exactly.
- The archived Phase-6 and Phase-7 reports matched the corresponding local
  files byte-for-byte.

## Git boundary

- Frozen parent: `20f652f5f8b180a2518798d0ed85aa3f48212908`
- Phase-A reviewed-v2 baseline commit:
  `f8038467bc7a99b519f6bec692a9ad9c06f8cd19`
- Annotated tag: `phase-a-final-reviewed-v2`
- Audit branch: `phase-b1-bottleneck-audit`

The baseline commit contains only the seven Phase-7 paths present in the
review package status record.  Phase-B1 specifications, the original review
ZIP, and all new audit outputs were deliberately excluded from that commit.

## Baseline regression gate

The frozen baseline was rerun in the `topo_sfr` Conda environment with warnings
treated as errors:

```text
python -m pytest -q -W error --junitxml=logs_phase_b1/pytest_baseline.xml tests
609 passed in 101.43s
```

- Text log SHA256:
  `183a49afeb2564bbefbf8bf279bf9088ef07050cd3cc60eee79eeb4ba5bfe6bf`
- JUnit XML SHA256:
  `a28642599d85b3541f1e5b50ab30858ddf4965a20df3a2f4ec45336a6b9e539c`

## Immutable legacy evidence

`artifacts_phase_b1/baseline_manifest.json` records every file, size, and
SHA256 under each legacy evidence root.  Verification immediately after
creation passed.

| Legacy root | Present | Files | Bytes | Logical tree SHA256 |
|---|---:|---:|---:|---|
| `artifacts/` | yes | 890 | 42,062,673 | `775a3268aae3452b0119a28d6e2888d9122bbb221495c8343b24233d3403a44c` |
| `results/` | yes | 18,097 | 1,139,239,970 | `f401ef3727403092ba9097ce40f4136f11e703c515d47800eb7767851fe2cd7d` |
| `figures/` | no | 0 | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The absence of a top-level `figures/` directory is expected: the Phase-A
figures are contained below `results/` and are covered by that tree hash.
Manifest SHA256 at creation:
`9fc9717d3725f4d1fe89cea987e1c241f7333aa031b76b6ecc14e17bde5ab4c4`.

During Phase B1, `artifacts/`, `results/`, and `figures/` are read-only.  New
evidence is written only to `artifacts_phase_b1/`, `results_phase_b1/`,
`figures_phase_b1/`, `logs_phase_b1/`, and `progress_phase_b1/`.  The baseline
manifest will be reverified before the review archive is built.
