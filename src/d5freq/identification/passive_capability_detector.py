"""Causal passive detector for control-relevant BESS capability changes."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True,slots=True)
class Detection:
    detected:bool
    index:int|None
    source:str
    score:float

@dataclass
class PassiveCapabilityDetector:
    dt_s:float=.1
    window_s:float=5.0
    residual_threshold_pu:float=.008
    consecutive_s:float=2.0

    def detect(self,command:np.ndarray,power:np.ndarray)->Detection:
        """Use issued command and measured power only; labels are not inputs."""
        u=np.asarray(command,float);y=np.asarray(power,float);w=round(self.window_s/self.dt_s);need=round(self.consecutive_s/self.dt_s)
        # Nominal causal actuator prediction.
        pred=np.zeros_like(y);delay=round(.2/self.dt_s);alpha=1-np.exp(-self.dt_s/.2)
        for k in range(1,len(y)):
            target=u[max(0,k-delay)];pred[k]=pred[k-1]+alpha*(target-pred[k-1])
        score=np.convolve(np.abs(y-pred),np.ones(w)/w,mode='same')
        above=score>self.residual_threshold_pu;run=0;idx=None
        for k,value in enumerate(above):
            run=run+1 if value else 0
            if run>=need:idx=k-need+1;break
        if idx is None:return Detection(False,None,'nominal',float(score.max()))
        lo=max(0,idx);hi=min(len(y),idx+round(8/self.dt_s));uu=u[lo:hi];yy=y[lo:hi]
        lags=range(0,round(2.5/self.dt_s)+1);corr=[]
        for lag in lags:
            if lag==0:a,b=uu,yy
            else:a,b=uu[:-lag],yy[lag:]
            corr.append(np.corrcoef(a,b)[0,1] if len(a)>3 and np.std(a)>0 and np.std(b)>0 else -1)
        best_lag=int(np.nanargmax(corr))*self.dt_s
        settled=yy[min(len(yy)-1,round(2.0/self.dt_s)):]
        robust_rate=float(np.quantile(np.abs(np.diff(settled))/self.dt_s,.90)) if len(settled)>1 else 0.0
        if np.max(np.abs(yy))<.035:source='headroom'
        elif robust_rate<.009:source='ramp'
        elif best_lag>1.0:source='delay'
        else:source='ramp'
        return Detection(True,idx,source,float(score[idx]))
