"""Map H1--H6 to locked Phase-I evidence without imputing missing stages."""

from __future__ import annotations

import pandas as pd


def hypothesis_table(method_gate_passed: bool) -> pd.DataFrame:
    return pd.DataFrame([
        ("H1", "SUPPORTED", "factor-separated capability mechanisms in corrected full-event validation"),
        ("H2", "SUPPORTED", "actual-POI observer confusion audit"),
        ("H3", "SUPPORTED_WITH_FINITE_SAMPLE_SCOPE", "60-episode coverage and no-excitation audit"),
        ("H4", "SUPPORTED_FOR_HARD_SAFETY_SEMANTICS", "contract floor separated from online performance and violation cases"),
        ("H5", "SUPPORTED" if method_gate_passed else "NOT_SUPPORTED", "I6 paired corrected validation Gate"),
        ("H6", "SUPPORTED_WITH_CONDITIONAL_SCOPE", "local RPI, finite bridge, infeasibility and equation-code replay"),
    ], columns=["hypothesis", "status", "evidence"])
