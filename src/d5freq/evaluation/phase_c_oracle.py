"""Evaluation-only Phase C Oracle hierarchy and rolling multiple-shooting NMPC."""
from __future__ import annotations
from dataclasses import dataclass
import math, os, sys, time
from pathlib import Path
import numpy as np

_DLL=None
def _casadi():
    global _DLL
    if os.name=='nt' and _DLL is None and hasattr(os,'add_dll_directory'):
        p=Path(sys.prefix)/'Library'/'bin'
        if p.is_dir():
            _DLL=os.add_dll_directory(str(p))
            if str(p) not in os.environ.get('PATH','').split(os.pathsep):
                os.environ['PATH']=str(p)+os.pathsep+os.environ.get('PATH','')
    import casadi as ca
    return ca

@dataclass(frozen=True,slots=True)
class OracleLevel:
    name:str
    evaluation_only:bool
    current_full_state:bool
    current_capability:bool
    future_load:bool
    future_regime:bool

ORACLE_LEVELS={
 'O0':OracleLevel('O0',True,False,False,False,False),
 'O1':OracleLevel('O1',True,True,False,False,False),
 'O2':OracleLevel('O2',True,True,True,False,False),
 'O3':OracleLevel('O3',True,True,True,True,True),
}

@dataclass(frozen=True,slots=True)
class NMPCSolve:
    command:np.ndarray
    success:bool
    status:str
    wall_time_s:float
    iterations:int
    max_constraint_residual:float
    local_optimum_only:bool=True
    global_optimality_claim:bool=False

class RollingMultipleShootingNMPC:
    """Four-block nonlinear multiple-shooting regulator.

    O2 receives current capability bounds only.  Its disturbance prediction is
    causal persistence supplied by the same estimator as the nominal baseline.
    """
    evaluation_only=True
    uses_future_load=False
    uses_future_regime=False
    global_optimality_claim=False

    def __init__(self,level:str='O2',period_s:float=4.0,horizon_blocks:int=4,
                 inertia_s:tuple[float,float]=(5.0,4.5),
                 damping:tuple[float,float]=(1.0,1.0),tie_coefficient:float=.07):
        if level not in ORACLE_LEVELS: raise ValueError(level)
        self.level=ORACLE_LEVELS[level];self.period_s=period_s;self.n=horizon_blocks
        self.inertia_s=inertia_s;self.damping=damping;self.tie_coefficient=tie_coefficient
        self._build();self._warm=None

    def _build(self):
        ca=_casadi(); n=self.n; dt=self.period_s
        # x=[omega1,omega2,tie,pm1,pm2,pb1,pb2]
        X=ca.MX.sym('X',7,n+1);U=ca.MX.sym('U',4,n)
        P=ca.MX.sym('P',7+2+4) # current state, causal load estimate, bounds
        g=[X[:,0]-P[:7]];cost=0
        f0=50.;h1,h2=self.inertia_s;d1,d2=self.damping;ktie=2*math.pi*f0*self.tie_coefficient
        b1=21.;b2=21.
        for k in range(n):
            x=X[:,k];u=U[:,k];bd=P[9:13]
            # Stable 0.2 s internal integration within every shooting block.
            xn=x; sub=.2
            for _ in range(round(dt/sub)):
                pm1n=xn[3]+sub*.01*ca.tanh((u[0]-xn[3])/.01)
                pm2n=xn[4]+sub*.01*ca.tanh((u[2]-xn[4])/.01)
                tar1=bd[1]*ca.tanh(u[1]/ca.fmax(bd[1],1e-5));tar2=bd[3]*ca.tanh(u[3]/ca.fmax(bd[3],1e-5))
                decay=math.exp(-sub/.15)
                pb1n=tar1+(xn[5]-tar1)*decay;pb2n=tar2+(xn[6]-tar2)*decay
                w1n=xn[0]+sub*(pm1n+pb1n-P[7]-d1*xn[0]-xn[2])/(2*h1)
                w2n=xn[1]+sub*(pm2n+pb2n-P[8]-d2*xn[1]+xn[2])/(2*h2)
                tn=xn[2]+sub*ktie*(xn[0]-xn[1])
                xn=ca.vertcat(w1n,w2n,tn,pm1n,pm2n,pb1n,pb2n)
            g.append(X[:,k+1]-xn)
            ace1=b1*x[0]+x[2];ace2=b2*x[1]-x[2]
            cost += 2e4*(ace1**2+ace2**2)+15*ca.sumsqr(u)
            if k: cost += 5*ca.sumsqr(U[:,k]-U[:,k-1])
        cost += 5e4*ca.sumsqr(X[:2,n])
        z=ca.vertcat(ca.reshape(X,-1,1),ca.reshape(U,-1,1));gg=ca.vertcat(*g)
        opts={'ipopt.print_level':0,'print_time':False,'ipopt.max_iter':200,'ipopt.tol':1e-7,'ipopt.sb':'yes'}
        self._solver=ca.nlpsol('phase_c_nmpc','ipopt',{'x':z,'p':P,'f':cost,'g':gg},opts)
        self._nx=7*(n+1);self._ng=7*(n+1)

    def solve(self,x:np.ndarray,load_estimate:np.ndarray,bounds:np.ndarray)->NMPCSolve:
        ca=_casadi(); bounds=np.maximum(np.asarray(bounds,float),1e-5)
        x=np.asarray(x,float);p=np.r_[x,np.asarray(load_estimate,float),bounds]
        xnodes=np.tile(x[:,None],(1,self.n+1));u=np.zeros((4,self.n));z0=np.r_[xnodes.ravel(order='F'),u.ravel(order='F')]
        if self._warm is not None and self._warm.shape==z0.shape:z0=self._warm
        lbx=np.r_[np.full(self._nx,-np.inf),np.tile(-bounds,self.n)]
        ubx=np.r_[np.full(self._nx,np.inf),np.tile(bounds,self.n)]
        t=time.perf_counter()
        try:
            sol=self._solver(x0=z0,p=p,lbx=lbx,ubx=ubx,lbg=np.zeros(self._ng),ubg=np.zeros(self._ng))
            z=np.asarray(sol['x']).ravel();self._warm=z
            stats=self._solver.stats();cmd=z[self._nx:self._nx+4]
            residual=float(np.max(np.abs(np.asarray(sol['g']).ravel())))
            ok=bool(stats.get('success',False)) and residual<1e-5
            return NMPCSolve(cmd,ok,str(stats.get('return_status')),time.perf_counter()-t,int(stats.get('iter_count',0)),residual)
        except Exception as exc:
            return NMPCSolve(np.zeros(4),False,type(exc).__name__,time.perf_counter()-t,0,float('inf'))

class NominalDeployableNMPC(RollingMultipleShootingNMPC):
    evaluation_only=False
    def __init__(self,**kwargs): super().__init__(level='O0',**kwargs)
