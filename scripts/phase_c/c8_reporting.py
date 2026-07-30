"""Generate locked C8 tables, figures and negative-result interpretation."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np,pandas as pd,matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[2]
def savefig(name):plt.tight_layout();plt.savefig(ROOT/'figures_phase_c'/'C8'/name,dpi=160);plt.close()
def main():
    out=ROOT/'results_phase_c'/'C8';rep=ROOT/'research_outputs'/'results';rep.mkdir(parents=True,exist_ok=True);fig=ROOT/'figures_phase_c'/'C8';fig.mkdir(parents=True,exist_ok=True)
    d=pd.read_parquet(out/'episode_metrics.parquet');analysis=json.loads((out/'final_analysis.json').read_text());prop='proposed_set_adaptive_mpc';best=analysis['best_deployable_baseline']
    # Success-first paired four-cell table.
    ev=d[~d.failure_class.isin(['not_evaluated','not_applicable'])];p=ev[ev.method==prop].set_index(['split','seed','plant']);b=ev[ev.method==best].set_index(['split','seed','plant']);rows=[]
    for split in ('final_known','final_ood'):
        idx=p.loc[split].index.intersection(b.loc[split].index);ps=p.loc[split].loc[idx].scientific_success.astype(bool);bs=b.loc[split].loc[idx].scientific_success.astype(bool)
        rows.append({'split':split,'both_success':int((ps&bs).sum()),'only_proposed_success':int((ps&~bs).sum()),'only_baseline_success':int((~ps&bs).sum()),'both_fail':int((~ps&~bs).sum())})
    pd.DataFrame(rows).to_csv(out/'success_first_four_cell.csv',index=False)
    # Worst cases and all failure/solver ledgers.
    worst=ev.sort_values(['scientific_success','max_abs_frequency_hz','ace_iae'],ascending=[True,False,False]).head(30);worst.to_csv(out/'worst_cases.csv',index=False)
    d[d.failure_class!='success'][['split','seed','plant','scenario','sg','method','failure_class']].to_csv(out/'failure_ledger.csv',index=False)
    d[(d.failure_class=='solver_failure')|((d.solver_success.notna())&(d.solver_success<.95))].to_csv(out/'solver_failures.csv',index=False)
    # Scene/method tables and Pareto/cost sensitivity.
    scene=ev.groupby(['split','scenario','method'])[['scientific_success','frequency_iae','ace_iae','max_abs_frequency_hz']].mean().reset_index();scene.to_csv(out/'scene_balanced_summary.csv',index=False)
    means=ev.groupby(['split','method'])[['frequency_iae','ace_iae','ibr_mileage_pu','sg_mileage_pu','scientific_success','wall_p99_s']].mean().reset_index();means.to_csv(out/'summary_table.csv',index=False)
    costs=[]
    for label,we,wm,wv in [('low',.2,.05,5),('medium',1,.2,20),('high',3,.5,100)]:
        for r in means.itertuples(index=False):costs.append({'cost_case':label,'split':r.split,'method':r.method,'weighted_cost':we*r.frequency_iae+wm*(r.ibr_mileage_pu+r.sg_mileage_pu)+wv*(1-r.scientific_success)})
    pd.DataFrame(costs).to_csv(out/'cost_sensitivity.csv',index=False)
    ab=pd.DataFrame([{'ablation':'no_online_update','proxy':'fixed_allocation','status':'evaluated_proxy'},{'ablation':'no_uncertainty_tightening','proxy':'nominal_mpc','status':'evaluated_proxy'},{'ablation':'no_backup','proxy':'none','status':'not_applicable_no_fallback_invoked'},{'ablation':'hard_source_label','proxy':'none','status':'not_evaluated'},{'ablation':'no_library_prior','proxy':'proposed','status':'not_applicable_zero_prior_implementation'}]);ab.to_csv(out/'ablation_status.csv',index=False)
    # Figures and their source data.
    plot=means[means['split']=='final_known'];x=np.arange(len(plot));plt.figure(figsize=(9,4));plt.bar(x,plot.scientific_success);plt.xticks(x,plot.method,rotation=55,ha='right');plt.ylabel('scientific success');savefig('success_rates.png')
    plt.figure(figsize=(6,4));
    for split,mark in [('final_known','o'),('final_ood','x')]:
        q=means[means['split']==split];plt.scatter(q.frequency_iae,q.ace_iae,marker=mark,label=split)
        for r in q.itertuples():plt.annotate(r.method.replace('_mpc',''),(r.frequency_iae,r.ace_iae),fontsize=6)
    plt.xlabel('frequency IAE');plt.ylabel('ACE IAE');plt.legend();savefig('pareto.png')
    plt.figure(figsize=(8,4));plt.bar(x,1000*plot.wall_p99_s);plt.xticks(x,plot.method,rotation=55,ha='right');plt.ylabel('mean episode P99 action time [ms]');savefig('compute_time.png')
    wp=worst.head(12);plt.figure(figsize=(8,4));plt.bar(np.arange(len(wp)),wp.max_abs_frequency_hz);plt.xticks(np.arange(len(wp)),[f'{r.method}:{r.seed}' for r in wp.itertuples()],rotation=60,ha='right',fontsize=6);plt.ylabel('max |frequency| [Hz]');savefig('worst_cases.png')
    # Reuse auditable numeric validation for unit/energy figures.
    mv=json.loads((ROOT/'results_phase_c/C2/model_validation.json').read_text());pd.DataFrame([mv]).to_csv(out/'unit_energy_figure_data.csv',index=False)
    plt.figure(figsize=(5,3.5));plt.bar(['analytic RoCoF','numeric RoCoF'],[mv['rocof_expected_hz_s'],mv['rocof_numeric_hz_s']]);plt.ylabel('Hz/s');savefig('unit_rocof_validation.png')
    plt.figure(figsize=(5,3.5));plt.bar(['max energy residual'],[mv['max_energy_residual_mwh']]);plt.yscale('log');plt.ylabel('MWh');savefig('energy_conservation.png')
    # Compact model block diagram.
    plt.figure(figsize=(8,3));ax=plt.gca();ax.axis('off');boxes=[(.05,'Measurements'),(.27,'Load/set\nestimator'),(.51,'Set-adaptive\nresponsibility'),(.76,'Plant A/B')]
    for xpos,label in boxes:ax.text(xpos,.5,label,ha='center',va='center',bbox={'boxstyle':'round','facecolor':'white'}); 
    for a,bx in zip(boxes[:-1],boxes[1:]):ax.annotate('',xy=(bx[0]-.09,.5),xytext=(a[0]+.09,.5),arrowprops={'arrowstyle':'->'});savefig('model_block_diagram.png')
    # Reports.
    (rep/'FINAL_EXPERIMENT_REPORT.md').write_text(f'''# Final experiment report\n\nAll 1280 registered method statuses are retained: 984 success, 136 frequency/ACE failures, and 160 optional O3 `not_evaluated`. The best deployable baseline is `{best}`. Proposed and baseline both have 100% known/OOD success, but proposed continuous performance is worse: known frequency/ACE aggregate improvements are -2.95%/-32.94%; OOD -37.32%/-121.31%. The method-success Gate therefore fails.\n''',encoding='utf-8')
    (rep/'NEGATIVE_RESULTS.md').write_text('''# Negative results\n\nThe scientific problem is material and passively identifiable under the registered C4/C5 tests, but the selected C6-A implementation is not superior to conservative robust capability-set MPC. Its continuous responsibility rule adds IBR use without enough performance benefit, especially for OOD compound changes. No post-final tuning or controller substitution was performed. O2 also fails many final performance episodes despite solver success, so it is not a general exact-optimal ceiling.\n''',encoding='utf-8')
    (rep/'WORST_CASES.md').write_text('''# Worst cases\n\nThe complete ordered table is `results_phase_c/C8/worst_cases.csv`. The largest deviations concentrate in O2 and fixed/nominal allocation under capability mismatch. Proposed has no scientific failure but loses to the robust SG-dominant baseline in aggregate IAE.\n''',encoding='utf-8')
    (rep/'RESULTS_INTERPRETATION.md').write_text('''# Results interpretation\n\nC4 establishes that current capability information can be valuable relative to a nominal MPC under a qualified materiality design. C5 establishes early external-I/O detection in its registered single-mechanism traces. C8 does not establish that the chosen passive set-adaptive responsibility law converts those facts into improvement over the strongest conservative baseline. This is evidence against the method as currently implemented, not evidence that the physical problem is immaterial.\n''',encoding='utf-8')
    print(json.dumps({'rows':len(d),'failures':d.failure_class.value_counts().to_dict(),'best':best,'method_gate':'FAIL'},indent=2))
if __name__=='__main__':main()
