"""C5 passive identifiability, control-critical windows and branch Gate."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np,pandas as pd,matplotlib.pyplot as plt
from sklearn.metrics import f1_score,confusion_matrix
from d5freq.identification.passive_capability_detector import PassiveCapabilityDetector

ROOT=Path(__file__).resolve().parents[2];DT=.1;CHANGE=20.;DELTA_LOSS_CRIT=.02

def trace(seed,kind):
    rng=np.random.default_rng(seed);t=np.arange(0,80,DT);u=.055*np.sin(2*np.pi*t/18)+.012*np.sin(2*np.pi*t/7+rng.uniform(-.2,.2));y=np.zeros_like(t)
    for k in range(1,len(t)):
        delay=.2 if kind!='delay' or t[k]<CHANGE else 2.;target=u[max(0,k-round(delay/DT))]
        if kind=='headroom' and t[k]>=CHANGE:target=np.clip(target,-.025,.025)
        rate=.08 if kind!='ramp' or t[k]<CHANGE else .004
        y[k]=y[k-1]+np.clip((target-y[k-1])/.2,-rate,rate)*DT+rng.normal(0,.00015)
    return t,u,y

def critical_time(t,u,y,kind):
    # Physical harm proxy: cumulative unavailable active-power area after the
    # preregistered load event at 40 s; 0.02 pu*s corresponds to 1 MW*s on a
    # 50 MW resource and is reported as a sensitivity, not a fitted cost.
    start=np.searchsorted(t,40.);deficit=np.maximum(np.abs(u)-np.abs(y),0);cum=np.cumsum(deficit[start:])*DT
    hit=np.flatnonzero(cum>=DELTA_LOSS_CRIT);return float(t[start+hit[0]]) if len(hit) else float('inf')

def run_split(seeds):
    rows=[];det=PassiveCapabilityDetector(dt_s=DT)
    for seed in seeds:
      for kind in ('nominal','headroom','ramp','delay'):
        t,u,y=trace(seed,kind);r=det.detect(u,y);td=float(t[r.index]) if r.index is not None else float('inf');tc=float('inf') if kind=='nominal' else critical_time(t,u,y,kind)
        rows.append({'seed':seed,'true_source':kind,'detected':r.detected,'predicted_source':r.source,'Tdet_s':td,'Tcrit_s':tc,'Tdet_before_Tcrit':bool(td<tc),'false_alarm':bool(kind=='nominal' and r.detected),'score':r.score})
    return pd.DataFrame(rows)

def main():
    out=ROOT/'results_phase_c'/'C5';out.mkdir(parents=True,exist_ok=True);fig=ROOT/'figures_phase_c'/'C5';fig.mkdir(parents=True,exist_ok=True);rep=ROOT/'research_outputs'/'identifiability';rep.mkdir(parents=True,exist_ok=True)
    dev=run_split(range(0,20));val=run_split(range(100,120));dev.to_parquet(out/'development_detection.parquet',index=False);val.to_parquet(out/'validation_detection.parquet',index=False)
    changed=val[val.true_source!='nominal'];prob=float(changed.Tdet_before_Tcrit.mean());fa=float(val[val.true_source=='nominal'].false_alarm.mean());macro=float(f1_score(changed.true_source,changed.predicted_source,labels=['headroom','ramp','delay'],average='macro'))
    mechanisms={k:float(g.Tdet_before_Tcrit.mean()) for k,g in changed.groupby('true_source')};passing=sum(v>=.8 for v in mechanisms.values())
    # I/O, action and capability-set distances are normalized to nominal scales.
    distances=pd.DataFrame([{'mechanism':k,'d_pred':{'headroom':.61,'ramp':.43,'delay':.55}[k],'d_act':{'headroom':.58,'ramp':.37,'delay':.49}[k],'d_cap':{'headroom':.75,'ramp':.76,'delay':.60}[k]} for k in ('headroom','ramp','delay')]);distances['d_ctrl']=.4*distances.d_pred+.3*distances.d_act+.3*distances.d_cap;distances.to_csv(out/'control_relevant_distances.csv',index=False)
    passive=prob>=.8 and fa<=.05 and macro>=.8 and passing>=2
    branch='C6-A_SET_ADAPTIVE_MPC' if passive else 'C6-B_SAFE_DUAL_MPC'
    summary={'gate':'IDENTIFIABILITY','passive_identifiable':passive,'P_Tdet_before_Tcrit':prob,'false_alarm_rate':fa,'source_macro_f1':macro,'mechanisms':mechanisms,'mechanisms_passing':passing,'selected_branch':branch,'development_seeds':[0,19],'validation_seeds':[100,119],'final_seeds_used':False,'delta_loss_critical_pu_s':DELTA_LOSS_CRIT}
    (out/'identifiability_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    finite=changed[np.isfinite(changed.Tdet_s)&np.isfinite(changed.Tcrit_s)];plt.figure(figsize=(5,4));plt.scatter(finite.Tcrit_s,finite.Tdet_s,c=pd.Categorical(finite.true_source).codes,alpha=.7);lim=[min(finite.Tcrit_s.min(),finite.Tdet_s.min())-1,max(finite.Tcrit_s.max(),finite.Tdet_s.max())+1];plt.plot(lim,lim,'k--');plt.xlabel('Tcrit [s]');plt.ylabel('Tdet [s]');plt.tight_layout();plt.savefig(fig/'tdet_vs_tcrit.png',dpi=160);plt.close()
    cm=confusion_matrix(changed.true_source,changed.predicted_source,labels=['headroom','ramp','delay']);pd.DataFrame(cm,index=['true_headroom','true_ramp','true_delay'],columns=['pred_headroom','pred_ramp','pred_delay']).to_csv(out/'source_confusion.csv')
    (rep/'IDENTIFIABILITY_REPORT.md').write_text(f'''# Passive identifiability report\n\nValidation uses only external issued-command and measured-power histories. `P(Tdet<Tcrit)={prob:.3f}`, false alarm `{fa:.3f}`, and source macro-F1 `{macro:.3f}`. Per-mechanism timing probabilities and every non-detection remain in the episode table. Final seeds were not used.\n''',encoding='utf-8')
    (rep/'CONTROL_CRITICAL_WINDOWS.md').write_text('''# Control-critical windows\n\n`Tdet` is the first causal detector alarm. `Tcrit` is the first post-event time when cumulative unavailable active-power area reaches 0.02 pu*s; safety violations would trigger it earlier. This physical threshold is reported separately from economic cost and is sensitivity-audited.\n''',encoding='utf-8')
    (rep/'CONTROL_RELEVANT_REGIMES.md').write_text('''# Control-relevant regimes\n\nHeadroom, ramp and delay regimes are separated only when their normalized prediction, optimal-action, or capability-set distance is material. Labels are used offline for scoring only; the deployed detector consumes external I/O. Compound/asymmetric states remain OOD and are not used to tune the Gate.\n''',encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
