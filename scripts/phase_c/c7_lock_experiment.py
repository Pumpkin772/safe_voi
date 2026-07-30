"""Write C7 preregistration artifacts and execute a non-final dry run."""
from __future__ import annotations
import csv,hashlib,json
from pathlib import Path
import numpy as np
from d5freq.controllers.set_adaptive_mpc import SetAdaptiveMPC
from d5freq.experiments.phase_c_protocol import *

ROOT=Path(__file__).resolve().parents[2]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    rep=ROOT/'research_outputs'/'experiment';rep.mkdir(parents=True,exist_ok=True);out=ROOT/'results_phase_c'/'C7';out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for split,seeds,ood in [('final_known',FINAL_KNOWN_SEEDS,False),('final_ood',FINAL_OOD_SEEDS,True)]:
      for seed in seeds:
       for plant in ('A','B'):
        rows.append({'split':split,'seed':seed,'plant':plant,'scenario':scenario_for_seed(seed,ood),'sg_capability':('adequate','scarce','critical')[seed%3],'duration_s':180.0,'control_period_s':2.0})
    with (rep/'SCENARIO_MANIFEST.csv').open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    with (rep/'CONTROLLER_MANIFEST.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['method','status','information']);
        for m in METHODS:w.writerow([m,'required' if m!='O3_clairvoyant_ceiling' else 'optional','measured_only' if not m.startswith('O') else 'evaluation_only'])
    (rep/'METRIC_DICTIONARY.md').write_text('''# Metric dictionary\n\nScientific outcome is classified first. Safety metrics: max absolute frequency, RoCoF, ACE/tie/resource violations. Performance metrics: frequency and ACE IAE/RMS, settling, SG/IBR energy and mileage. Diagnostic metrics: Tdet, Tcrit, set coverage/width and confusion. Computational metrics: solve mean/P95/P99, timeout, infeasibility and fallback. `not_evaluated` and `not_applicable` are statuses, never failures.\n''',encoding='utf-8')
    (rep/'STATISTICAL_ANALYSIS_PLAN.md').write_text('''# Locked statistical analysis plan\n\n1. Report the paired four-cell success table first. 2. Compare continuous outcomes on common-success pairs and retain a failure-penalty sensitivity. 3. Use scenario-balanced ratios of aggregate sums, never the mean episode-wise ratio as the sole percentage. 4. Bootstrap seeds within scenario for 95% CIs and report paired absolute differences. 5. Holm-adjust the two primary proposed-vs-best-baseline metrics. 6. Report known and OOD separately.\n''',encoding='utf-8')
    (rep/'ABLATION_PLAN.md').write_text('''# Locked ablation plan\n\nC6-A ablations are: no online update; no uncertainty tightening; no backup; hard source label replacing the set; no library prior. Safe-dual information-objective ablations are not applicable because branch B was rejected. Fixed worst-set versus online shrinkage is represented by the robust baseline versus proposed method.\n''',encoding='utf-8')
    (rep/'COMPUTE_BUDGET.md').write_text('''# Compute budget\n\nThe final manifest has 160 plant/scenario cases and eight method statuses. Physical integration is 0.01 s for 180 s. Up to eight local workers are allowed. O3 is optional and may be `not_evaluated`; that status is excluded from failure rates. No controller/threshold/configuration edits are allowed after a final result is observed.\n''',encoding='utf-8')
    # Dry run exercises API/failure schema with development seed 0 only.
    assert_tuning_seeds([0]);c=SetAdaptiveMPC();obs=np.zeros(13);a=c.action(obs,np.zeros(2));dry={'seed':0,'final_seed':False,'command_finite':bool(np.isfinite(a.command).all()),'failure_classes':list(FAILURE_CLASSES),'methods':list(METHODS),'manifest_rows':len(rows)}
    (out/'dry_run.json').write_text(json.dumps(dry,indent=2),encoding='utf-8')
    locks={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'configs/phase_c/final.yaml',rep/'SCENARIO_MANIFEST.csv',rep/'CONTROLLER_MANIFEST.csv',rep/'STATISTICAL_ANALYSIS_PLAN.md',rep/'ABLATION_PLAN.md']}
    (out/'LOCKED_HASHES.json').write_text(json.dumps(locks,indent=2),encoding='utf-8')
    print(json.dumps({'dry_run':dry,'locked_hashes':locks},indent=2))
if __name__=='__main__':main()
