# Native ANDES Plant B

`direction5freq.models.plant_b_andes_full.PlantBAndesFull` loads the bundled
Kundur `kundur_vsc.xlsx` system and retains its buses, lines, four GENROU
machines, exciters, TGOV1 governors and implicit RMS/DAE solve. Two shunts are
used as native BESS POI injections. Load, BESS and governor signals enter the
native equations every physical step. The controller sees only the common
public observation. `TDS.config.test_init=1`: initialization diagnostics are
preserved, while convergence and algebraic residuals are reported separately.
No reduced state-space layer or injected Gaussian residual is used.
