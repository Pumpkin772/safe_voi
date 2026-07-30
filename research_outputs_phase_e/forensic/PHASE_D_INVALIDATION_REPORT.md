# Phase D invalidation and Phase E recovery baseline

## Decision

The Phase D status `PASSIVE_CAPABILITY_SET_NOT_SUPPORTED` is withdrawn as a scientific conclusion and retained only as the outcome of the old protocol. The binding replacement is:

`PHASE_D_GATE_INVALIDATED_BY_CLOSED_LOOP_AND_EVALUATION_DEFECTS`

## Frozen evidence

- ZIP SHA256: `ed471534e162d5748cb8d735d9ca1f017ac6ad2c7ab9c125c6351e6ef658ebc6`
- Git commit: `11f0379e0e7bd9b1ddf97be8d88b7f918bbb52e9`
- Frozen tag: `direction1-phase-d-negative-reviewed`
- ZIP members: 244
- Manifest-managed files: 240/240, all hashes matched
- Governance files read and hashed: 20/20

No Phase D CSV, Parquet, JSON, source or figure was overwritten. The evidence index points into the read-only ZIP.

## Independently reproduced decisive defects

- Tiny `1e-6 pu` initial frequency perturbation under the registered PI reached 0.578261 Hz and ended at 0.378008 Hz after 200 s.
- The registered PI raised background-load maximum frequency deviation from 0.004417 Hz without SFR to 0.571385 Hz.
- Delay truth changed at 45.0 s; the candidate set changed at 45.1 s and became the correct singleton at 45.6 s, while no alarm/update time was recorded.
- The old deficit-area loss time was 46.4 s; it is not a frequency/ACE/tie/constraint or matched-Oracle loss definition.
- Static source audit confirms the all-failed path selected the final allowed candidate instead of a preregistered Pareto/minimum-violation candidate.

All fields in the independent reproduction matched the registered expected output to `1e-10` absolute tolerance or exact categorical equality.

## Consequence

Phase E must first establish stable 2/4 s nominal control and physical Plant A/B, then qualify a rolling current-capability Oracle and test H1 before any passive/active identification conclusion. Phase D remains immutable historical evidence, not paper support for passive impossibility.
