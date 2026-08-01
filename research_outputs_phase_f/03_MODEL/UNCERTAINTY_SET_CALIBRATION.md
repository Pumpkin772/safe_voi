# Residual uncertainty calibration

Only seeds 0--19 calibrate the set.  Seeds 20--39 are used once for coverage.
Factors are written explicitly in the manifest and shuffled independently.
For 1/2/4/6-step windows the componentwise 99.5th development quantile is
inflated by 1.50; the independently
computed dense-delay hull remainder is then included.  Validation coverage is
reported without deleting any window.  The set supports only registered-set
finite-horizon claims, not arbitrary OEM modes.
