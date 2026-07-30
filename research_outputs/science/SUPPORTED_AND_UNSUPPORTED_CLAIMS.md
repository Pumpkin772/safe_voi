# Supported and Unsupported Claims Before Experiments

## Supported as motivation or protocol

- Public NERC reports document material IBR performance/model-quality deficiencies and the need for verified, maintained RMS/EMT representations.
- Existing peer-reviewed work establishes black-box/switching IBR identification, data-driven frequency control, DeePC/Koopman MPC, robust adaptive MPC, predictive safety filters, dual-control concepts, and multi-area AGC as neighboring foundations.
- The exact intersection of unannounced capability-set change, external-I/O-only `Tdet<Tcrit`, multi-area ACE responsibility, and Gate-selected safe reallocation is not covered by any record in the verified 50-source matrix.
- Phase C has a valid, falsifiable protocol for determining whether that intersection is scientifically material.

## Not yet supported

- That the scientific problem is material on either corrected plant.
- That passive identification is fast enough.
- That active probing is needed or safe.
- That any proposed Phase C method outperforms deployable baselines.
- That Plant B is an OEM or EMT validation.
- Any publication-readiness claim.

## Permanently prohibited claims

- First black-box IBR multimode model, first Koopman/DeePC frequency controller, or innovation based on classification accuracy.
- Recovery of an OEM's true internal mode or parameters.
- Global optimality of a local NMPC solve.
- Global nonlinear stability/safety for arbitrary IBRs.
- Complete EMT validation unless a genuine, validated EMT/OEM plant is added.
