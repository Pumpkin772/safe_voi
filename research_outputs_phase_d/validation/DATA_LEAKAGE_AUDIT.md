# D2 information-boundary audit

The simulator owns true load, capability, energy and native states. Deployable controller inputs are limited to measured frequency/ACE/tie-line, SG mechanical power, BESS POI power, issued commands and a shared causal estimator. The Plant B bridge is simulator infrastructure and never exposes GENROU states, true load/capability, SoC or future events to a controller.
