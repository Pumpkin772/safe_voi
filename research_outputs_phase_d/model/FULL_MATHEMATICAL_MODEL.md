# Direction1 corrected physical model

Plant A uses `omega=(f-f0)/f0`, `df=f0*omega`, two swing equations, signed tie-line exchange, common ACE, fixed droop/PFR, held upper SFR, and governor/turbine dynamics with GRC applied at mechanical power. BESS PFR and SFR share one feasible set containing headroom, apparent-current, ramp, delay, availability and one-step energy constraints; MWh energy is never repaired by SoC projection.

Plant B is native ANDES 2.0.0 `kundur_vsc.xlsx`: 10 buses, 15 branches, four GENROU machines, native TGOV1/exciter dynamics and native algebraic network equations. The external physical BESS actuator is connected at buses 5 and 9 through `P_b=-g_b V_b^2`. This active injection is solved inside the native bus equation and changes generator electrical torque and swing dynamics. The direct native Alter schedule and causal external bridge used the same registered load and BESS signals.
