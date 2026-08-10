# M2 validation attempt V1 invalidation

Status: `INVALIDATED_DECISIVE_CODE_ERROR`

The first nine completed Plant-A method rows are preserved.  During the first
high/low pair audit, the low-value VOI arm correctly made zero probe calls but
did not reproduce the nominal contract arm.  Source inspection established
that the new validation adapter had instantiated the historical
`DCSVContractRecourseMPC` for the arm labelled contract-only, whereas the
M1-locked VOI controller and M1 comparison used the same weighted
`ContractOnlyRollingRobustMPC` core.

This is a baseline-class integration error, not an algorithm or Gate failure.
No M1 weight, threshold, probe, scenario magnitude, or scientific standard was
changed.  V1 seeds 5200--5202 were consumed and will not be reused.  V2 uses a
new independent validation seed range and retains this directory in the final
failure ledger and review package.
