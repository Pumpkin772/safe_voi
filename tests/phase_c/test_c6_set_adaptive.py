from __future__ import annotations
import inspect,numpy as np
from d5freq.controllers.set_adaptive_mpc import CapabilitySetEstimator,SetAdaptiveMPC

def test_deployed_api_cannot_accept_true_hidden_information():
    names=set(inspect.signature(SetAdaptiveMPC.action).parameters)
    assert not names.intersection({'true_regime','true_parameters','true_load','future_load','soc'})

def test_set_resets_conservatively_after_unavailable_output():
    e=CapabilitySetEstimator();e.update(.05,.049);e.update(.05,.049)
    assert e.interval.lower_pu>0
    e.update(.05,0);c=e.update(.05,0)
    assert c.lower_pu==0 and c.contains(0)

def test_backup_uses_sg_only_on_invalid_measurement():
    a=SetAdaptiveMPC().action(np.full(13,np.nan),np.zeros(2))
    assert a.used_backup and a.command[1]==0 and a.command[3]==0
