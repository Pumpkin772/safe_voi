# Solver and environment status

The completed D0–D3 path uses NumPy/SciPy, Pandas/PyArrow, Matplotlib, scikit-learn utilities, and ANDES 2.0.0. Plant B uses the native ANDES Kundur VSC DAE/network solve. D3 estimation is causal and does not invoke a commercial optimizer.

CasADi/IPOPT, CVXPY, MOSEK, and Gurobi are present in the reusable `topo_sfr` environment for historical and planned MPC work. Because H2 failed before D4, no Direction1 rolling NMPC or tube-MPC solve was implemented or evaluated. Therefore no Oracle/CRCS solver qualification is claimed, and neither `gurobi.lic` nor `mosek.lic` is packaged.
