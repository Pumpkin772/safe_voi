# Direction1 Phase D literature review

The verified corpus contains 56 records, including 32 from 2022–2026 and 49 (87.5%) peer-reviewed papers or formal standards. It spans black-box and switching IBR modeling, native RMS/EMT validation, multi-area ACE control, data-enabled predictive control, set-membership adaptive MPC, robust tubes, safe/dual control, and industry model-quality evidence.

## Evidence synthesis

External-I/O modeling of opaque IBRs and switching dynamic-state estimation are established, but they do not prove that natural frequency-control trajectories identify a *current feasible active-power/ramp/delay/energy set* before control harm. Robust adaptive and tube-MPC theory provides set contraction, recursive-feasibility, and robust-constraint tools under bounded disturbances, but the surveyed papers do not combine those tools with multi-area ACE/tie-line control, hidden IBR service capability, causal passive updates, and a native networked RMS plant. Recent nonlinear tube/set-membership work strengthens the theoretical neighborhood but remains generic or preprint evidence.

The literature therefore supports testing—rather than assuming—the Direction1 claim: a control-relevant capability set estimated from public histories may reduce fixed worst-case conservatism while retaining a tube and SG terminal backup. Novelty is conditional on passing H1–H4; this review makes no priority or effectiveness claim.

## Metadata correction

The launch text called the Lu–Cannon 2019 anchor “TCST.” Verified metadata identify it as the 2019 American Control Conference paper `Robust Adaptive Tube Model Predictive Control`, DOI `10.23919/ACC.2019.8814456`. The record is corrected here.
