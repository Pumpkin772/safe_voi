# E2 Plant A/B and native-interface validation

Plant A is the proof/large-experiment aggregate model.  Plant B is the native ANDES Kundur RMS/DAE model and is not expected to numerically match Plant A.  Plant-B validation instead applies one identical load/BESS signal through (i) the causal external bridge and (ii) native ANDES Alter events.  Their maximum interpolated COI-frequency difference is 4.017e-05 Hz; both retain the native network and converge.  The observed BESS injection reaches 0.00504503 pu on the external 1000 MVA base and the native bus residual P99 is 1.877e-08 pu.
