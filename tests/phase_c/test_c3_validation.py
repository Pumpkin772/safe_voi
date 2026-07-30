from __future__ import annotations
import inspect
import numpy as np
from d5freq.models.bess_capability import BESSParameters,BESSState,capability
from d5freq.models.linearization import swing_tie_jacobian,swing_tie_rhs
from d5freq.models.plant_a_two_area import PlantAParameters,PlantAState,PlantATwoArea

def test_analytic_jacobian_matches_central_difference() -> None:
    p=PlantAParameters(); a=swing_tie_jacobian(p); n=np.zeros((3,3)); eps=1e-7
    for j in range(3):
        d=np.zeros(3); d[j]=eps
        n[:,j]=(swing_tie_rhs(d,p)-swing_tie_rhs(-d,p))/(2*eps)
    assert np.max(np.abs(a-n)) < 1e-9

def test_energy_boundary_collapses_outward_capability() -> None:
    p=BESSParameters()
    lo=capability(BESSState(energy_mwh=p.soc_min*p.energy_mwh),p,0.1)
    hi=capability(BESSState(energy_mwh=p.soc_max*p.energy_mwh),p,0.1)
    assert lo.upper_pu == 0 and hi.lower_pu == 0

def test_observation_contract_has_no_hidden_arguments() -> None:
    names=set(inspect.signature(PlantATwoArea.observation).parameters)
    assert not names.intersection({'regime','load_pu','true_load','energy','soc'})
    p=PlantATwoArea(); s=PlantAState.equilibrium(p.params)
    assert len(p.observation(s,np.zeros(4))) == 13
