# Selected grid-load observer

Selected: `ACTUAL_POI_AUGMENTED_SLOW_LOAD_STATE`. The causal balance equation
uses measured frequency/tie, SG mechanical power, actual BESS POI power and
actual slow-reserve power. A backward derivative is causally filtered and the
persistent load is one augmented slow state; it is not reintroduced as a new
incident each control period. Issued command is absent from the selected API.
The command-driven implementation exists only as an ineligible diagnostic
comparator.
