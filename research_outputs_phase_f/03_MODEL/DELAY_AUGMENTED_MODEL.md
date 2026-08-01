# Delay-augmented prediction model

For each BESS delay vertex, exact ZOH integration splits current and previously
applied commands.  SG input delay stays at the public 0.2 s nominal value.
The augmented state is [nine Plant-A states, four actually applied previous
commands, two BESS energies].  All online scenarios must share one command
sequence.  Linear interpolation between the five registered vertices is not
claimed exact: its dense-grid curvature remainder is computed componentwise
and added to the residual uncertainty set.
