"""Locked C8 known/OOD final experiment and success-first analysis."""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor
from collections import deque
import argparse,json,time
from pathlib import Path
import numpy as np,pandas as pd,matplotlib.pyplot as plt
from d5freq.controllers.set_adaptive_mpc import SetAdaptiveMPC
from d5freq.evaluation.phase_c_oracle import RollingMultipleShootingNMPC
from d5freq.experiments.phase_c_protocol import METHODS,scenario_for_seed
from d5freq.models.bess_capability import capability
from d5freq.models.plant_a_two_area import PlantATwoArea,PlantAState,CapabilityRegime
from d5freq.models.plant_b_native_rms import NativeRMSPlantB,PlantBState

ROOT=Path(__file__).resolve().parents[2];DT=.01;PERIOD=2.;DURATION=180.

def scenario_state(name,t):
    h=[1.,1.];r=[1.,1.];a=[1.,1.];delay=[.2,.2]
    if name=='headroom' and t>=30:h=[.25,.25]
    elif name=='ramp' and t>=30:r=[.25,.25]
    elif name=='delay' and t>=30:delay=[2.,2.]
    elif name=='service_disabled' and t>=30:a=[0.,0.]
    elif name=='asymmetric' and t>=30:h=[.15,1.]
    elif name=='compound_headroom_delay' and t>=30:h=[.25,.25];delay=[2.,2.]
    elif name=='gradual_drift' and t>=30:h=[max(.2,1-(t-30)/100),max(.2,1-(t-30)/100)]
    elif name=='unknown_three_stage':
        if 30<=t<70:h=[.5,.5]
        elif 70<=t<110:h=[.2,.2]
        elif t>=110:h=[.8,.8]
    elif name=='current_limit_q' and t>=30:h=[.45,.45]
    elif name=='multiple_switches':
        if 30<=t<65:a=[0.,0.]
        elif 95<=t<130:r=[.2,.2]
        elif t>=150:h=[.25,.25]
    return CapabilityRegime(tuple(a),tuple(h),tuple(r),tuple(delay))

def run_episode(task):
    split,seed,plant_name,scenario,sg_level,method=task
    if method=='O3_clairvoyant_ceiling':return {'split':split,'seed':seed,'plant':plant_name,'scenario':scenario,'sg':sg_level,'method':method,'failure_class':'not_evaluated','scientific_success':np.nan,'solver_success':np.nan}
    rng=np.random.default_rng(seed);p=PlantATwoArea(dt_s=DT) if plant_name=='A' else NativeRMSPlantB(dt_s=DT)
    soc=.105 if scenario=='energy_low' else .5;x=PlantAState.equilibrium(p.params,soc) if plant_name=='A' else PlantBState.equilibrium(p.params,soc)
    proposed=SetAdaptiveMPC(sg_bound_pu={'adequate':.1,'scarce':.06,'critical':.04}[sg_level]);command=np.zeros(4);applied=np.zeros(4);next_control=0;prev_w=np.zeros(2);load_hat=np.zeros(2);freq=[];aces=[];ties=[];wall=[];solver_ok=[];fallback=[];alpha=[];energy0=sum(s.energy_mwh for s in x.bess);ibr_mileage=0.;sg_mileage=0.;last_pb=np.zeros(2);last_pm=np.zeros(2);gain=np.ones(2)
    delay_buffers=[deque([0.]*205,maxlen=205),deque([0.]*205,maxlen=205)]
    oracle=None
    if method=='O2_current_capability_nmpc':
        kw={'inertia_s':(5.,4.5),'damping':(1.,1.),'tie_coefficient':.07} if plant_name=='A' else {'inertia_s':(9.,10.),'damping':(.6,.6),'tie_coefficient':0.}
        oracle=RollingMultipleShootingNMPC('O2',period_s=PERIOD,**kw)
    n=round(DURATION/DT)
    for k in range(n):
        t=k*DT;reg=scenario_state(scenario,t);obs=p.observation(x,command);w=obs[:2]/50.;tie=obs[4]
        if k:
            dw=(w-prev_w)/DT
            h=np.array([p.params.area1.inertia_s,p.params.area2.inertia_s]) if plant_name=='A' else np.array([9.,10.]);d=np.array([1.,1.]) if plant_name=='A' else np.array([.6,.6])
            load_hat=np.clip([obs[5]+obs[7]-d[0]*w[0]-tie-2*h[0]*dw[0],obs[6]+obs[8]-d[1]*w[1]+tie-2*h[1]*dw[1]],-.12,.12)
        if k>=next_control:
            target=np.clip(load_hat-.35*obs[2:4],-.2,.2);tic=time.perf_counter()
            if method=='sg_only_pi':command=np.array([np.clip(-.22*obs[2],-.1,.1),0.,np.clip(-.22*obs[3],-.1,.1),0.])
            elif method in ('fixed_allocation','nominal_mpc'):command=np.array([.5*target[0],.5*target[0],.5*target[1],.5*target[1]])
            elif method=='rls_adaptive_mpc':
                for i in range(2):
                    if abs(command[2*i+1])>.01:gain[i]=np.clip(.9*gain[i]+.1*abs(obs[7+i]/command[2*i+1]),0,1)
                command=np.array([(1-.5*gain[0])*target[0],.5*gain[0]*target[0],(1-.5*gain[1])*target[1],.5*gain[1]*target[1]])
            elif method=='robust_capability_set_mpc':command=np.array([np.clip(load_hat[0]-.2*obs[2],-.1,.1),0.,np.clip(load_hat[1]-.2*obs[3],-.1,.1),0.])
            elif method=='proposed_set_adaptive_mpc':
                act=proposed.action(obs,load_hat);command=act.command;fallback.append(act.used_backup);alpha.append(float(act.responsibility.mean()))
            elif method=='O2_current_capability_nmpc':
                bp=(p.params.area1.bess,p.params.area2.bess) if plant_name=='A' else (p.params.bess,p.params.bess)
                bb=np.array([capability(x.bess[i],bp[i],PERIOD,availability=reg.availability[i],headroom_fraction=reg.headroom_fraction[i],ramp_fraction=reg.ramp_fraction[i]).upper_pu for i in range(2)])
                xx=np.array([w[0],w[1],tie,obs[5],obs[6],obs[7],obs[8]]);sol=oracle.solve(xx,load_hat,np.array([{'adequate':.1,'scarce':.06,'critical':.04}[sg_level],bb[0],{'adequate':.1,'scarce':.06,'critical':.04}[sg_level],bb[1]]));command=sol.command;solver_ok.append(sol.success)
            wall.append(time.perf_counter()-tic);next_control+=round(PERIOD/DT)
        # External communication delay applies only to SFR command.
        applied=command.copy()
        for i in range(2):
            delay_buffers[i].append(command[2*i+1]);lag=min(round(reg.delay_s[i]/DT),len(delay_buffers[i])-1);applied[2*i+1]=delay_buffers[i][-1-lag]
        mag=(.02,.04,.06,.08)[seed%4];sign=-1 if seed%5==0 else 1;area=seed%2;load=np.zeros(2)
        if t>=40:load[area]=sign*mag
        x=p.step(x,applied,load,reg)[0] if plant_name=='A' else p.step(x,applied,load,reg);oo=p.observation(x,command);freq.append(oo[:2]);aces.append(oo[2:4]);ties.append(oo[4]);pb=oo[7:9];pm=oo[5:7];ibr_mileage+=float(np.abs(pb-last_pb).sum());sg_mileage+=float(np.abs(pm-last_pm).sum());last_pb=pb.copy();last_pm=pm.copy();prev_w=w
    f=np.asarray(freq);ac=np.asarray(aces);scientific=bool(np.max(np.abs(f))<=.8 and np.max(np.abs(ac))<=.35);energy1=sum(s.energy_mwh for s in x.bess)
    return {'split':split,'seed':seed,'plant':plant_name,'scenario':scenario,'sg':sg_level,'method':method,'failure_class':'success' if scientific else 'frequency_or_ace_failure','scientific_success':scientific,'frequency_iae':float(DT*np.abs(f).sum()),'frequency_rms_hz':float(np.sqrt(np.mean(f*f))),'ace_iae':float(DT*np.abs(ac).sum()),'tie_iae':float(DT*np.abs(ties).sum()),'max_abs_frequency_hz':float(np.abs(f).max()),'max_abs_ace_pu':float(np.abs(ac).max()),'bess_energy_change_mwh':float(energy1-energy0),'ibr_mileage_pu':ibr_mileage,'sg_mileage_pu':sg_mileage,'solver_success':float(np.mean(solver_ok)) if solver_ok else 1.0,'wall_mean_s':float(np.mean(wall)),'wall_p99_s':float(np.quantile(wall,.99)),'fallback_fraction':float(np.mean(fallback)) if fallback else 0.0,'mean_ibr_responsibility':float(np.mean(alpha)) if alpha else np.nan}

def aggregate_analysis(df):
    evaluated=df[~df.failure_class.isin(['not_evaluated','not_applicable'])].copy();deploy=['sg_only_pi','fixed_allocation','nominal_mpc','rls_adaptive_mpc','robust_capability_set_mpc'];prop='proposed_set_adaptive_mpc'
    means=evaluated.groupby(['split','method'])[['frequency_iae','ace_iae','scientific_success','wall_p99_s','solver_success','fallback_fraction']].mean().reset_index()
    known=means[means['split']=='final_known'].copy();known['score']=known.frequency_iae+known.ace_iae;best=str(known[known.method.isin(deploy)].sort_values('score').iloc[0].method)
    results={'best_deployable_baseline':best,'splits':{}}
    for split in ('final_known','final_ood'):
        q=evaluated[evaluated.split==split];pv=q.pivot(index=['seed','plant','scenario','sg'],columns='method',values=['frequency_iae','ace_iae','scientific_success'])
        rec={}
        for metric in ('frequency_iae','ace_iae'):
            valid=pv[(metric,prop)].notna()&pv[(metric,best)].notna()&pv[('scientific_success',prop)].astype(bool)&pv[('scientific_success',best)].astype(bool);a=pv.loc[valid,(metric,prop)].to_numpy();b=pv.loc[valid,(metric,best)].to_numpy();point=float(1-a.sum()/b.sum());rng=np.random.default_rng(20260730);vals=[]
            for _ in range(3000):idx=rng.integers(0,len(a),len(a));vals.append(1-a[idx].sum()/b[idx].sum())
            rec[metric]={'aggregate_improvement':point,'ci':[float(np.quantile(vals,.025)),float(np.quantile(vals,.975))],'common_success_n':int(len(a))}
        ps=float(q[q.method==prop].scientific_success.mean());bs=float(q[q.method==best].scientific_success.mean());rec['proposed_success']=ps;rec['baseline_success']=bs;rec['success_difference_pp']=100*(ps-bs);results['splits'][split]=rec
    pm=evaluated[evaluated.method==prop];results['solver_infeasibility']=float(1-pm.solver_success.mean());results['wall_p99_s']=float(pm.wall_p99_s.max());results['fallback_fraction']=float(pm.fallback_fraction.mean());return results,means

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dry-run',action='store_true');args=ap.parse_args();out=ROOT/'results_phase_c'/'C8';out.mkdir(parents=True,exist_ok=True);fig=ROOT/'figures_phase_c'/'C8';fig.mkdir(parents=True,exist_ok=True)
    if args.dry_run:tasks=[('development',0,'A','headroom','critical',m) for m in METHODS]
    else:
        manifest=pd.read_csv(ROOT/'research_outputs/experiment/SCENARIO_MANIFEST.csv');tasks=[(r.split,int(r.seed),r.plant,r.scenario,r.sg_capability,m) for r in manifest.itertuples(index=False) for m in METHODS]
    with ProcessPoolExecutor(max_workers=8) as pool:rows=list(pool.map(run_episode,tasks,chunksize=1))
    df=pd.DataFrame(rows)
    if args.dry_run:
        print(df[['method','failure_class','scientific_success']].to_string(index=False));return
    df.to_parquet(out/'episode_metrics.parquet',index=False);analysis,means=aggregate_analysis(df);means.to_csv(out/'method_summary.csv',index=False);(out/'final_analysis.json').write_text(json.dumps(analysis,indent=2),encoding='utf-8')
    status=df.groupby(['split','method','failure_class']).size().rename('count').reset_index();status.to_csv(out/'failure_counts.csv',index=False)
    known=means[means['split']=='final_known'];plt.figure(figsize=(9,4));plt.bar(np.arange(len(known))-.18,known.frequency_iae,.36,label='frequency IAE');plt.bar(np.arange(len(known))+.18,known.ace_iae,.36,label='ACE IAE');plt.xticks(np.arange(len(known)),known.method,rotation=55,ha='right');plt.legend();plt.tight_layout();plt.savefig(fig/'known_performance.png',dpi=160);plt.close()
    print(json.dumps(analysis,indent=2))
if __name__=='__main__':main()
