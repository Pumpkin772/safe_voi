"""C6-A control-relevant set-adaptive MPC responsibility layer."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True,slots=True)
class CapabilityInterval:
    lower_pu:float
    upper_pu:float
    confidence:float=.99

    def contains(self,value:float)->bool:return self.lower_pu-1e-12<=value<=self.upper_pu+1e-12

@dataclass
class CapabilitySetEstimator:
    """Set-membership update from external command/output pairs only."""
    rating_pu:float=.1
    noise_bound_pu:float=.001
    lower_pu:float=0.0
    upper_pu:float=.1
    mismatch_count:int=0

    def update(self,issued_pu:float,measured_pu:float)->CapabilityInterval:
        u,y=float(issued_pu),float(measured_pu);res=abs(u-y)
        if abs(u)>.015 and res>.008:self.mismatch_count+=1
        else:self.mismatch_count=max(0,self.mismatch_count-1)
        if self.mismatch_count>=2:
            self.lower_pu=0.0
            self.upper_pu=min(self.upper_pu,max(abs(y)+3*self.noise_bound_pu,.003))
        elif abs(u)>.01 and res<=.008:
            self.lower_pu=max(self.lower_pu,min(abs(y)-3*self.noise_bound_pu,self.rating_pu))
        self.lower_pu=float(np.clip(self.lower_pu,0,self.upper_pu))
        return self.interval

    @property
    def interval(self)->CapabilityInterval:return CapabilityInterval(self.lower_pu,self.upper_pu)

@dataclass(frozen=True,slots=True)
class AdaptiveAction:
    command:np.ndarray
    responsibility:np.ndarray
    used_backup:bool
    set_width:np.ndarray
    reason:str

class SetAdaptiveMPC:
    """Deployable set-adaptive responsibility MPC with robust backup.

    The public action API accepts measurements and a causal load estimate.  It
    has no parameter for true capability, regime, SoC, load or future events.
    """
    evaluation_only=False
    uses_true_regime=False
    uses_true_parameters=False
    uses_future_information=False

    def __init__(self,sg_bound_pu:float=.1,bess_rating_pu:float=.1,ace_gain:float=.35):
        self.sg_bound_pu=sg_bound_pu;self.bess_rating_pu=bess_rating_pu;self.ace_gain=ace_gain
        self.sets=[CapabilitySetEstimator(bess_rating_pu),CapabilitySetEstimator(bess_rating_pu)]

    def action(self,observation:np.ndarray,load_estimate:np.ndarray)->AdaptiveAction:
        y=np.asarray(observation,float);load=np.asarray(load_estimate,float)
        if y.shape[0]<13 or load.shape!=(2,) or not np.isfinite(y).all() or not np.isfinite(load).all():
            return self.backup(y)
        ace=y[2:4];pb=y[7:9];issued=y[10:13:2]
        intervals=[self.sets[i].update(issued[i],pb[i]) for i in range(2)]
        target=np.clip(load-self.ace_gain*ace,-(self.sg_bound_pu+self.bess_rating_pu),self.sg_bound_pu+self.bess_rating_pu)
        command=np.zeros(4);alpha=np.zeros(2)
        for i,c in enumerate(intervals):
            alpha[i]=min(.5,c.lower_pu/max(self.bess_rating_pu,1e-12))
            ub=np.clip(alpha[i]*target[i],-c.lower_pu,c.lower_pu)
            ug=np.clip(target[i]-ub,-self.sg_bound_pu,self.sg_bound_pu)
            command[2*i:2*i+2]=[ug,ub]
        return AdaptiveAction(command,alpha,False,np.array([c.upper_pu-c.lower_pu for c in intervals]),'set_adaptive_feasible')

    def backup(self,observation:np.ndarray)->AdaptiveAction:
        y=np.asarray(observation,float);ace=y[2:4] if y.size>=4 and np.isfinite(y[2:4]).all() else np.zeros(2)
        c=np.array([np.clip(-.25*ace[0],-self.sg_bound_pu,self.sg_bound_pu),0.,np.clip(-.25*ace[1],-self.sg_bound_pu,self.sg_bound_pu),0.])
        return AdaptiveAction(c,np.zeros(2),True,np.array([s.upper_pu-s.lower_pu for s in self.sets]),'measurement_or_estimator_invalid')
