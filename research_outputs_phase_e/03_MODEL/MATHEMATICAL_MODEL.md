# Direction1 Phase-E mathematical model

Internal frequency is `omega_i=(f_i-f0)/f0`.  Plant A implements

`2 H_i domega_i/dt = p_m,i + p_b,i - p_L,i - D_i omega_i - signed_tie_i`

and `dp_12/dt = 2*pi*f0*T_12*(omega_1-omega_2)`.  ACE uses the documented operator bias `B_i=21 pu-power/pu-frequency` and signed tie exchange.  Governors and turbines retain droop, time constants, mechanical-power bounds, and a derivative-level GRC.  Boundary landing is applied only at physical valve/mechanical bounds and never to frequency, energy, or controller-integrator states.

Fixed local BESS PFR and upper SFR form one requested target before the shared causal delay channel.  The delayed request is intersected with active/reactive apparent-power, asymmetric headroom, availability, ramp, and one-step energy bounds.  Energy is integrated in MWh with separate charge/discharge efficiency; SoC is never projected.

The supervisory ACE PI is selected on an exact ZOH discretization at 2 or 4 s.  Its augmented state includes the integral action and the previous command needed for the nominal 0.2 s within-period delay.  Saturation invokes explicit integrator back-calculation.  A separate discrete LQI baseline uses the same delayed augmentation and is retained for later fair baseline comparison.

Plant B is native ANDES `kundur/kundur_vsc.xlsx`: the original four GENROU machines, TGOV1 governors, exciters, buses, branches, and algebraic equations remain active.  BESS power is a voltage-dependent Norton injection at buses 5 and 9 and therefore enters the native active-power balance and electrical torque.  The public callback exposes no hidden capability or future event.
