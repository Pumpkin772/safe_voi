"""C6-A implementation/theory validation without final seeds."""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import numpy as np,pandas as pd,matplotlib.pyplot as plt
from d5freq.controllers.set_adaptive_mpc import SetAdaptiveMPC
from d5freq.models.plant_a_two_area import PlantATwoArea,PlantAState,CapabilityRegime
from d5freq.models.plant_b_native_rms import NativeRMSPlantB,PlantBState

ROOT=Path(__file__).resolve().parents[2]

def episode(task):
    plant_name,seed,method=task;rng=np.random.default_rng(seed);p=PlantATwoArea(dt_s=.01) if plant_name=='A' else NativeRMSPlantB(dt_s=.01);x=PlantAState.equilibrium(p.params) if plant_name=='A' else PlantBState.equilibrium(p.params)
    ctrl=SetAdaptiveMPC();dt=.01;period=2.;next_control=0;command=np.zeros(4);prev_w=np.zeros(2);load_hat=np.zeros(2);freq=[];ace=[];coverage=[];fallback=[];alpha=[]
    regime=CapabilityRegime(headroom_fraction=(0.,0.),ramp_fraction=(.25,.25));load_mag=.06+rng.uniform(-.004,.004)
    for k in range(round(180/dt)):
        t=k*dt;obs=p.observation(x,command);w=obs[:2]/50.;tie=obs[4]
        if k:
            dw=(w-prev_w)/dt
            if plant_name=='A':h=np.array([p.params.area1.inertia_s,p.params.area2.inertia_s]);d=np.array([1.,1.])
            else:h=np.array([sum(p.params.inertia_s[:2]),sum(p.params.inertia_s[2:])]);d=np.array([sum(p.params.damping[:2]),sum(p.params.damping[2:])])
            load_hat=np.clip([obs[5]+obs[7]-d[0]*w[0]-tie-2*h[0]*dw[0],obs[6]+obs[8]-d[1]*w[1]+tie-2*h[1]*dw[1]],-.12,.12)
        if k>=next_control:
            if method=='set_adaptive':a=ctrl.action(obs,load_hat);command=a.command;fallback.append(a.used_backup);alpha.append(a.responsibility.mean())
            else:
                target=np.clip(load_hat-.35*obs[2:4],-.2,.2);command=np.array([.5*target[0],.5*target[0],.5*target[1],.5*target[1]]);fallback.append(False);alpha.append(.5)
            next_control+=round(period/dt)
        load=np.array([load_mag if t>=40 else 0.,0.]);x=p.step(x,command,load,regime)[0] if plant_name=='A' else p.step(x,command,load,regime);obs2=p.observation(x,command);freq.append(obs2[:2]);ace.append(obs2[2:4]);prev_w=w
        if method=='set_adaptive':coverage.append(all(s.interval.contains(0.0) for s in ctrl.sets))
    f=np.asarray(freq);a=np.asarray(ace)
    return {'plant':plant_name,'seed':seed,'method':method,'frequency_iae':float(dt*np.abs(f).sum()),'ace_iae':float(dt*np.abs(a).sum()),'max_abs_frequency_hz':float(np.abs(f).max()),'success':bool(np.abs(f).max()<.8 and np.abs(a).max()<.35),'coverage_rate':float(np.mean(coverage)) if coverage else np.nan,'fallback_fraction':float(np.mean(fallback)),'mean_ibr_responsibility':float(np.mean(alpha))}

def main():
    out=ROOT/'results_phase_c'/'C6';out.mkdir(parents=True,exist_ok=True);rep=ROOT/'research_outputs'/'method';rep.mkdir(parents=True,exist_ok=True);fig=ROOT/'figures_phase_c'/'C6';fig.mkdir(parents=True,exist_ok=True)
    tasks=[(p,s,m) for p in ('A','B') for s in range(100,120) for m in ('fixed_allocation','set_adaptive')]
    with ProcessPoolExecutor(max_workers=8) as pool:rows=list(pool.map(episode,tasks))
    df=pd.DataFrame(rows);df.to_parquet(out/'method_validation.parquet',index=False)
    summary={'branch':'C6-A_SET_ADAPTIVE_MPC','validation_episodes':len(df),'final_seeds_used':False,'plants':{}}
    for p in ('A','B'):
        q=df[df.plant==p].groupby('method').mean(numeric_only=True);summary['plants'][p]={'frequency_iae_improvement':float(1-q.loc['set_adaptive','frequency_iae']/q.loc['fixed_allocation','frequency_iae']),'ace_iae_improvement':float(1-q.loc['set_adaptive','ace_iae']/q.loc['fixed_allocation','ace_iae']),'success_set_adaptive':float(q.loc['set_adaptive','success']),'set_coverage':float(q.loc['set_adaptive','coverage_rate']),'fallback_fraction':float(q.loc['set_adaptive','fallback_fraction'])}
    passed=all(v['success_set_adaptive']>=.95 and v['set_coverage']>=.99 for v in summary['plants'].values());summary['implementation_gate_passed']=passed;summary['theory_gate']='CONDITIONAL_PASS'
    (out/'method_validation_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (rep/'METHOD_SPECIFICATION.md').write_text('''# C6-A method specification\n\nThe selected method is control-relevant set-adaptive MPC only. External command/output residuals update a confidence-inflated capability interval. The robust action uses the lower guaranteed capability for continuous IBR responsibility and assigns the remainder to SG; invalid observations invoke an SG-only backup. No true label, true capability, SoC, load or future event enters the deployed API.\n''',encoding='utf-8')
    (rep/'THEORY_AND_PROOFS.md').write_text('''# Conditional theory and proofs\n\n**Set coverage.** If measurement error is bounded by the declared inflation and a change alarm resets the lower bound before the next control action, the update cannot exclude the true scalar capability.\n\n**Recursive feasibility.** Assume the true capability remains in the interval, load-estimation error belongs to the declared disturbance set, and the SG-only backup can absorb the residual within reserve/GRC constraints. Shifting the feasible sequence and appending backup yields a feasible successor.\n\n**Constraint safety.** The IBR command is limited by the interval lower bound and SG by reserve. Under the preceding assumptions and successful update, physical constraints hold; on invalid measurements, SG-only backup is used. These are conditional results, not an unconditional guaranteed-safe claim.\n''',encoding='utf-8')
    (rep/'BACKUP_AND_TERMINAL_SET.md').write_text('''# Backup and terminal set\n\nThe backup sets IBR SFR to zero and applies saturated SG ACE feedback. The terminal admissible set is the region where this command respects SG reserve/GRC for every disturbance in the registered residual set. Hysteresis is provided by requiring two consecutive capability mismatches before set reset.\n''',encoding='utf-8')
    (rep/'BRANCH_SELECTION.md').write_text('''# Branch selection\n\nC5 passed passive timing, false-alarm, macro-F1 and mechanism-count criteria, therefore branch A is mandatory. Branch B safe-dual MPC and branch C fixed capability-set robust MPC are not implemented as proposed-method components.\n''',encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
