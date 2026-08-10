# A0 historical freeze

The completed DCSV-CR closure line is immutable historical evidence.

- frozen commit: `011fab97ef8f46dfc2eb0438cd7595ba46e3e0b7`
- annotated tag: `direction5-closure-negative-frozen`
- frozen status: `DIRECTION5_NEGATIVE_RESULT_CONFIRMED_AND_ARCHIVED`
- frozen artifact: `DIRECTION5_CLOSURE_CONFIRMATION_AND_MANUSCRIPT_SINGLE_REVIEW_PACKAGE.zip`
- frozen artifact bytes: `78511501`
- frozen artifact SHA256: `c68fc521622c405e87923293bc383ff377d7c3d1cebeff1981c45439556bc0f0`

ACCR-MPC uses new development seeds 200--249, validation seeds 250--299,
and final seeds 400--459. Historical final seeds and all historical results are
read-only. No old claim, result, or package is overwritten.

## Decisive A0 platform defect

The current physical BESS implementation placed local frequency-responsive PFR
and remote SFR into the same command-delay pipeline. The historical normal1h
audit showed that all controller families became unstable for the delay-change
scenario, including SG-only PI and the perfect-capability Oracle. Applying a
communications delay to local PFR creates an artificial delayed-feedback loop.

The ACCR execution line corrects this code defect by delaying only the remote
SFR command. PFR remains local and contemporaneous, while total POI power still
obeys the shared physical power, ramp, energy, and actuator constraints. The
repair changes no historical output and no registered Gate.
