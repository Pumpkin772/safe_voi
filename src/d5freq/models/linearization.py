"""Auditable small-signal blocks for the corrected two-area swing model."""
from __future__ import annotations
import math
import numpy as np
from .plant_a_two_area import PlantAParameters

def swing_tie_jacobian(params: PlantAParameters) -> np.ndarray:
    """Analytic d[domega1,domega2,dtie]/d[omega1,omega2,tie]."""
    h1,h2=params.area1.inertia_s,params.area2.inertia_s
    d1=params.area1.damping_pu_power_per_pu_frequency
    d2=params.area2.damping_pu_power_per_pu_frequency
    k=2*math.pi*params.nominal_frequency_hz*params.tie_coefficient_pu_per_rad
    return np.array([[-d1/(2*h1),0,-1/(2*h1)],[0,-d2/(2*h2),1/(2*h2)],[k,-k,0]],dtype=float)

def swing_tie_rhs(x: np.ndarray, params: PlantAParameters) -> np.ndarray:
    w1,w2,tie=np.asarray(x,dtype=float)
    h1,h2=params.area1.inertia_s,params.area2.inertia_s
    d1=params.area1.damping_pu_power_per_pu_frequency
    d2=params.area2.damping_pu_power_per_pu_frequency
    return np.array([(-d1*w1-tie)/(2*h1),(-d2*w2+tie)/(2*h2),2*math.pi*params.nominal_frequency_hz*params.tie_coefficient_pu_per_rad*(w1-w2)])
