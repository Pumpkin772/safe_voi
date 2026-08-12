# Numerical interpretation of near-zero perfect-information values

The boundary engine requests CLARABEL absolute gap and feasibility tolerances of
1e-7. Pilot robust-minus-perfect-information differences include small negative values
(down to roughly -6.4e-7), which are impossible in exact arithmetic because
\(\min\max\ge\max\min\). They therefore give a direct empirical scale for solver
subtraction error.

Accordingly, the initial 1e-8 map flag is only a *screening flag*, not a positive-value
classification. Before B1 is frozen:

1. values within the empirically determined numerical deadband will be recomputed at
   tighter tolerances;
2. no point is positive unless its full posterior net value is strictly positive and
   materially larger than the recomputed numerical uncertainty;
3. a near-zero or unresolved point remains unclassified; it is not counted as either a
   positive or zero-value success;
4. theorem-supported zero requires either a nonpositive registered perfect-information
   value outside numerical ambiguity or evaluation of every safe-probe perfect-posterior
   upper value;
5. validation and final claims use confidence intervals from independent closed-loop
   episodes, not optimizer objective subtraction alone.

This treatment is deliberately conservative and prevents solver noise from creating an
artificial positive region.

