# Locked science and decisions

"
        "The sole scientific question and H1–H4 are those in "
        "`research/direction1_phase_d_crcs_tube_mpc/02_LOCKED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md`.

"
        "## Binding decision

"
        "H2 is rejected. Validation joint truth coverage was 0.7946979167 (<0.95). "
        "Power/ramp/delay/energy coverage was 0.8632256944/0.9000486111/0.9804861111/1.0. "
        "Update-before-loss probabilities were delay 0, headroom 0.4166666667, and ramp 0; "
        "zero mechanisms met the required 0.8 threshold. False-alarm and pre-change-alarm "
        "rates were both 0.

"
        "The resulting status is **PASSIVE_CAPABILITY_SET_NOT_SUPPORTED**. D4–D6 controller "
        "development and D8 final controller experiments are not evaluated.
",
        encoding="utf-8",
    )
    (REPORTS / "SUPPORTED_AND_UNSUPPORTED_CLAIMS.md").write_text(
        Supported: the corrected Plant A and native ANDES Plant B pass the registered D2 physics/cross-model checks; the evaluated passive set estimator fails H2 under the registered natural closed-loop I/O protocol.

Not supported: passive-identifiable capability sets, Oracle materiality, CRCS-TMPC performance, recursive feasibility, known/OOD safety, Pareto improvement, or superiority to any baseline. No best baseline can be named because no Direction1 controller comparison was run. This negative result is not evidence that every possible passive estimator must fail.
