from __future__ import annotations
import numpy as np
from d5freq.evaluation.phase_c_oracle import ORACLE_LEVELS,RollingMultipleShootingNMPC

def test_oracle_information_hierarchy():
    assert not ORACLE_LEVELS['O2'].future_load and not ORACLE_LEVELS['O2'].future_regime
    assert ORACLE_LEVELS['O2'].current_capability
    assert ORACLE_LEVELS['O3'].future_load and ORACLE_LEVELS['O3'].future_regime

def test_o2_multiple_shooting_solve_quality():
    c=RollingMultipleShootingNMPC('O2')
    r=c.solve(np.array([-.001,0.,0.,0.,0.,0.,0.]),np.zeros(2),np.array([.1,.05,.1,.05]))
    assert r.success and r.max_constraint_residual<1e-5
    assert not r.global_optimality_claim and r.local_optimum_only
