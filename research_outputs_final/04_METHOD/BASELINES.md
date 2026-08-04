# Locked baselines

1. SG-only anti-windup PI;
2. fixed-allocation anti-windup PI;
3. nominal offset-free rolling MPC;
4. contract-only rolling robust MPC (primary fair comparator);
5. public-I/O model-adaptive rolling MPC;
6. evaluation-only true-capability rolling Oracle.

Every object named MPC returns nonempty predicted state, input and measured-SoC
energy sequences from a constrained rolling optimization. PI controllers are
never labeled MPC. The Oracle is excluded from deployable rankings.
