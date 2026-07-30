from __future__ import annotations
import numpy as np
from d5freq.identification.passive_capability_detector import PassiveCapabilityDetector

def _trace(kind):
    dt=.1;t=np.arange(0,80,dt);u=.055*np.sin(2*np.pi*t/18)+.012*np.sin(2*np.pi*t/7);y=np.zeros_like(t)
    for k in range(1,len(t)):
        delay=.2 if kind!='delay' or t[k]<20 else 2.;target=u[max(0,k-round(delay/dt))]
        if kind=='headroom' and t[k]>=20:target=np.clip(target,-.025,.025)
        rate=.08 if kind!='ramp' or t[k]<20 else .004
        y[k]=y[k-1]+np.clip((target-y[k-1])/.2,-rate,rate)*dt
    return t,u,y

def test_detector_finds_three_sources_after_change():
    d=PassiveCapabilityDetector()
    for kind in ('headroom','ramp','delay'):
        t,u,y=_trace(kind);r=d.detect(u,y)
        assert r.detected and t[r.index]>=18 and r.source==kind

def test_nominal_trace_has_no_alarm():
    _,u,y=_trace('nominal');assert not PassiveCapabilityDetector().detect(u,y).detected
