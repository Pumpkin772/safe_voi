# Verified Literature Review

## Corpus and verification

The locked corpus contains 50 high-relevance records: 45 journal, conference or standard records verified by exact DOI metadata, and five official-report/preprint sources verified by live HTTPS access. Forty-five records are formal peer-reviewed publications or a formal standard; 27 are later than 2021. `METADATA_VERIFICATION.json` records the automated count Gates and source status, while `LITERATURE_MATRIX.csv` records the requested question/model/mode/change/service/safety/data/limitation fields for every source.

## Black-box IBR dynamics and switching

Huang et al.'s 2026 IEEE Transactions on Smart Grid paper (doi:10.1109/TSG.2025.3647551) directly studies noisy-data learning of black-box IBRs with multiple unknown modes. The 2025 IEEE Transactions on Power Systems switching-state-estimation paper (doi:10.1109/TPWRS.2024.3523490), a 2025 PESGM neural state-estimation paper, Hammerstein–Wiener identification, and a 2025 Nature Communications dynamic-modeling paper broaden the evidence that opaque IBR dynamics can be inferred from measurements. None closes the specific loop from an unannounced capability change through `Tdet<Tcrit` to safe multi-area ACE responsibility transfer.

## IBR frequency control

Hierarchical coordinated fast frequency control (doi:10.1109/TPWRS.2021.3075641) and data-driven fast frequency control (doi:10.1109/TPWRS.2023.3337011) show that area-based IBR redispatch can improve bulk-grid frequency response. Related PESGM/AUPEC studies confirm a meaningful neighboring design space. Their focus is fast frequency response or known/learned behavior, not hidden power/ramp/delay/energy availability changing online during secondary regulation.

## Data-driven predictive control

DeePC, data-driven MPC with stability/robustness guarantees (doi:10.1109/TAC.2020.3000182), robust DeePC (doi:10.1109/TAC.2023.3241282), robust kernelized DeePC, output-feedback variants, DMD with control and Koopman MPC demonstrate credible alternatives to explicit OEM models. These methods require informative data and stated noise/model assumptions. They do not automatically maintain a physical capability set or distinguish load changes from capability changes before control harm.

## Robust/set-adaptive MPC

The set-membership line from constrained adaptive receding-horizon control (doi:10.1016/j.automatica.2014.10.036), recursive model-update robust MPC (doi:10.1016/j.automatica.2019.02.023), and robust adaptive tube MPC (doi:10.1002/RNC.5175; doi:10.1002/RNC.6814) provides the closest theoretical basis for C6-A/C6-C. It supplies truth-covering parameter sets, tubes, recursive feasibility and constraint-satisfaction conditions. Phase C must specialize those conditions to IBR capability, hidden load/SoC, multi-area ACE and backup allocation.

## Safe active identification and dual control

The dual-control survey (doi:10.1016/j.arcontrol.2017.11.001), learning-based MPC for safe exploration, active exploration in adaptive MPC, predictive safety filters (doi:10.1016/j.automatica.2021.109597), and contingency safe-learning MPC establish a principled C6-B basis. They also show why active probing cannot be assumed useful: it needs a robust safe set, backup feasibility and an information benefit that exceeds a locked budget.

## Multi-area AGC and native validation

Multi-area load-frequency MPC, tie-line-bias control and BESS-assisted LFC provide the ACE/tie-line reference architecture but mostly use aggregate known models. ANDES supplies open RMS/DAE infrastructure, while IEEE 2800-2022 and NERC's 2022–2025 event/model/EMT reports establish capability, model-quality and validation expectations. Phase C therefore uses a transparent Plant A and an independent native multi-machine network Plant B, and explicitly avoids calling either an OEM EMT model.

## Gap and novelty boundary

No verified source simultaneously contains all of: black-box capability-set change; ordinary external-I/O-only operation; unknown-load separation; a control-relevant rather than OEM-label regime; a measured `Tdet<Tcrit` Gate; multi-area ACE/tie-line responsibility transfer; a Gate-selected single adaptive/dual/robust branch; and Plant-A/native-Plant-B verification. The defensible novelty is this intersection and its falsification protocol—not any one component in isolation.
