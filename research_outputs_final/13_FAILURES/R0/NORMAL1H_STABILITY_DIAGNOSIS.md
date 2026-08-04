# Phase-I normal1h stability diagnosis

## Observed anomaly

- `I6-N-02` / `dcsv_mpc`: peak 2.239355 Hz, terminal recovery=False.
- `I6-N-02` / `fixed_allocation_pi`: peak 2.207466 Hz, terminal recovery=False.

The anomaly is shared by DCSV and fixed-allocation PI on `I6-N-02`, despite the
registered synthetic profile having no exceptional amplitude.  The PI
implementation integrates ACE before clipping and has no conditional
integration or back-calculation, so integral windup is a confirmed code defect.
The DCSV trace also repeatedly reaches the contract command limits.  The saved
normal episode parts contain command, actual BESS power, SoC, domain and solver
status, but omit frequency, ACE, SG valve/mechanical power and slow-reserve
states.  Consequently the exact divergence onset cannot be reconstructed from
the frozen trace and must not be over-attributed to a single component.

## Gate defect

Phase I checked only that six rows per method existed and that a provenance
string was non-null.  It did not enforce a normal-frequency quality threshold.
Moreover the profile is a seeded AR(1)+sinusoid synthetic trace, not a public
measured load record; the field name `real_normal1h_provenance` described real
simulation duration, not real-world data provenance.

## Required R2/R5 repair

1. anti-windup PI and explicit saturation diagnostics;
2. full frequency/ACE/tie/SG/BESS/slow-reserve normal trajectories;
3. a registered frequency-quality Gate;
4. public measured data when obtainable, otherwise an explicit `synthetic`
   label;
5. no normal-profile claim from a non-null string alone.
