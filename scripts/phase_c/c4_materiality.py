"""Preregistered C4 current-capability O2 materiality experiment."""
from __future__ import annotations
import csv,json,time,sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from d5freq.evaluation.phase_c_oracle import RollingMultipleShootingNMPC,NominalDeployableNMPC
from d5freq.models.bess_capability import capability
from d5freq.models.plant_a_two_area import PlantATwoArea,PlantAState,CapabilityRegime
from d5freq.models.plant_b_native_rms import NativeRMSPlantB,PlantBState

ROOT=Path(__file__).resolve().parents[2]
SEEDS=range(100,120);SG={'adequate':.10,'scarce':.06,'critical':.04}

def balanced_aggregate_ratio_ci(pivot,metric,draws=5000):
    """Scenario-balanced aggregate ratio with seed-within-scenario bootstrap."""
    scenarios=sorted(set(pivot.index.get_level_values('sg')));rng=np.random.default_rng(20260730)
    def effect(frame):
        ratios=[]
        for sg in scenarios:
            part=frame.xs(sg,level='sg');ratios.append(1-part[(metric,'O2')].sum()/part[(metric,'nominal_mpc')].sum())
        return float(np.mean(ratios))
    values=[]
    for _ in range(draws):
        parts=[]
        for sg in scenarios:
            part=pivot.xs(sg,level='sg');idx=rng.integers(0,len(part),len(part));sample=part.iloc[idx].copy();sample.index=pd.MultiIndex.from_arrays([range(len(sample)),[sg]*len(sample)],names=['seed','sg']);parts.append(sample)
        values.append(effect(pd.concat(parts)))
    return effect(pivot),[float(np.quantile(values,.025)),float(np.quantile(values,.975))]

def run_episode(model,seed,sg_level,method):
    rng=np.random.default_rng(seed);dt=model.dt_s;period=4.;steps=round(180/dt);next_control=0
    state=PlantAState.equilibrium(model.params) if isinstance(model,PlantATwoArea) else PlantBState.equilibrium(model.params)
    if isinstance(model,PlantATwoArea):
        model_kw={'inertia_s':(model.params.area1.inertia_s,model.params.area2.inertia_s),'damping':(model.params.area1.damping_pu_power_per_pu_frequency,model.params.area2.damping_pu_power_per_pu_frequency),'tie_coefficient':model.params.tie_coefficient_pu_per_rad}
    else:
        model_kw={'inertia_s':(sum(model.params.inertia_s[:2]),sum(model.params.inertia_s[2:])),'damping':(sum(model.params.damping[:2]),sum(model.params.damping[2:])),'tie_coefficient':0.0}
    ctrl=RollingMultipleShootingNMPC('O2',period_s=period,**model_kw) if method=='O2' else NominalDeployableNMPC(period_s=period,**model_kw)
    command=np.zeros(4);freq=[];ace=[];solver=[];wall=[];prev_w=np.zeros(2);load_hat=np.zeros(2)
    load_mag=.06+float(rng.uniform(-.004,.004)); regime=CapabilityRegime(headroom_fraction=(0.0,0.0),ramp_fraction=(.25,.25))
    for k in range(steps):
        t=k*dt;load=np.array([load_mag if t>=20 else 0.,0.])
        obs=model.observation(state,command); w=obs[:2]/50.;tie=obs[4]
        if k>0:
            dw=(w-prev_w)/dt
            if isinstance(model,PlantATwoArea):
                h=np.array([model.params.area1.inertia_s,model.params.area2.inertia_s]);d=np.array([model.params.area1.damping_pu_power_per_pu_frequency,model.params.area2.damping_pu_power_per_pu_frequency])
            else:
                h=np.array([sum(model.params.inertia_s[:2]),sum(model.params.inertia_s[2:])]);d=np.array([sum(model.params.damping[:2]),sum(model.params.damping[2:])])
            # Causal unknown-input estimate from measured power balance; no
            # true load or future sample is supplied to either controller.
            load_hat=np.clip(np.array([obs[5]+obs[7]-d[0]*w[0]-tie-2*h[0]*dw[0],obs[6]+obs[8]-d[1]*w[1]+tie-2*h[1]*dw[1]]),-.12,.12)
        if k>=next_control:
            x=np.array([w[0],w[1],tie,obs[5],obs[6],obs[7],obs[8]])
            if method=='O2':
                if isinstance(model,PlantATwoArea):
                    bp=(model.params.area1.bess,model.params.area2.bess)
                else: bp=(model.params.bess,model.params.bess)
                bb=np.array([capability(state.bess[i],bp[i],period,headroom_fraction=regime.headroom_fraction[i],ramp_fraction=regime.ramp_fraction[i]).upper_pu for i in range(2)])
            else: bb=np.array([.1,.1])
            result=ctrl.solve(x,load_hat,np.array([SG[sg_level],bb[0],SG[sg_level],bb[1]]));command=result.command
            solver.append(result.success);wall.append(result.wall_time_s);next_control += round(period/dt)
        state=model.step(state,command,load,regime)[0] if isinstance(model,PlantATwoArea) else model.step(state,command,load,regime)
        obs=model.observation(state,command);freq.append(obs[:2]);ace.append(obs[2:4])
        prev_w=w
    f=np.asarray(freq);a=np.asarray(ace); scientific=bool(np.max(np.abs(f))<=.8 and np.max(np.abs(a))<=.35)
    return {'plant':'A' if isinstance(model,PlantATwoArea) else 'B','seed':seed,'sg':sg_level,'method':method,
      'frequency_iae':float(dt*np.abs(f).sum()),'ace_iae':float(dt*np.abs(a).sum()),'max_abs_frequency_hz':float(np.max(np.abs(f))),
      'scientific_success':scientific,'failure_class':'success' if scientific else 'frequency_or_ace_failure',
      'solver_success_rate':float(np.mean(solver)),'solver_p99_s':float(np.quantile(wall,.99))}

def run_task(task):
    plant,sg,seed,method=task
    model=PlantATwoArea(dt_s=.01) if plant=='A' else NativeRMSPlantB(dt_s=.01)
    return run_episode(model,seed,sg,method)

def main():
    out=ROOT/'results_phase_c'/'C4';out.mkdir(parents=True,exist_ok=True);fig=ROOT/'figures_phase_c'/'C4';fig.mkdir(parents=True,exist_ok=True)
    if '--statistics-only' in sys.argv:
        df=pd.read_parquet(out/'episode_metrics.parquet')
    else:
        tasks=[(plant,sg,seed,method) for plant in ('A','B') for sg in SG for seed in SEEDS for method in ('nominal_mpc','O2')]
        with ProcessPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(run_task,tasks,chunksize=1))
        df=pd.DataFrame(rows);df.to_parquet(out/'episode_metrics.parquet',index=False)
    comparisons=[]
    for plant in ('A','B'):
      p=df[df.plant==plant].pivot(index=['seed','sg'],columns='method',values=['frequency_iae','ace_iae','scientific_success'])
      rec={'plant':plant}
      for metric in ('frequency_iae','ace_iae'):
       improvement,ci=balanced_aggregate_ratio_ci(p,metric);rec[metric+'_improvement']=improvement;rec[metric+'_ci']=ci;rec[metric+'_estimator']='scenario-balanced aggregate ratio with seed-within-scenario bootstrap'
      rec['failure_reduction_pp']=100*float(p[('scientific_success','O2')].mean()-p[('scientific_success','nominal_mpc')].mean())
      rec['o2_solver_success']=float(df[(df.plant==plant)&(df.method=='O2')].solver_success_rate.mean())
      rec['o2_p99_s']=float(df[(df.plant==plant)&(df.method=='O2')].solver_p99_s.max());comparisons.append(rec)
    passed=all((sum(c[m+'_improvement']>=.10 and c[m+'_ci'][0]>0 for m in ('frequency_iae','ace_iae'))>=2 or c['failure_reduction_pp']>=20) and c['o2_solver_success']>=.95 for c in comparisons)
    summary={'gate':'MATERIALITY','passed':passed,'episodes':len(df),'validation_seeds':[100,119],'final_seeds_used':False,'comparisons':comparisons,'oracle_claim':'current-capability rolling multi-action nonlinear multiple-shooting local NMPC; not exact globally optimal','validation_repair_rounds':2,'statistical_repair_only_after_rounds':True}
    (out/'materiality_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    plot=pd.DataFrame(comparisons);x=np.arange(2);w=.35;plt.figure(figsize=(6,3.8));plt.bar(x-w/2,100*plot.frequency_iae_improvement,w,label='frequency IAE');plt.bar(x+w/2,100*plot.ace_iae_improvement,w,label='ACE IAE');plt.axhline(10,color='k',ls='--');plt.xticks(x,plot.plant);plt.ylabel('mean paired improvement [%]');plt.legend();plt.tight_layout();plt.savefig(fig/'oracle_materiality.png',dpi=160);plt.close()
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
