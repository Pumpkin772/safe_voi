"""One-command Phase C stage orchestrator with final-lock protection."""
from __future__ import annotations
import argparse,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];STAGES=[f'C{i}' for i in range(10)]
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--config',default='configs/phase_c/master.yaml');ap.add_argument('--resume',action='store_true');ap.add_argument('--start-stage',choices=STAGES);ap.add_argument('--stop-after-stage',choices=STAGES);ap.add_argument('--dry-run',action='store_true');args=ap.parse_args()
    state=json.loads((ROOT/'progress/phase_status.json').read_text());start=STAGES.index(args.start_stage) if args.start_stage else 0;stop=STAGES.index(args.stop_after_stage) if args.stop_after_stage else 9
    plan=[]
    for stage in STAGES[start:stop+1]:
        status=state['stages'][stage];plan.append({'stage':stage,'status':status,'action':'reuse_verified_output' if status in ('PASSED','COMPLETED_WITH_LIMITATIONS') else 'run_stage_script'})
    print(json.dumps({'config':args.config,'resume':args.resume,'dry_run':args.dry_run,'final_seed_lock':state['final_seed_results_observed'],'plan':plan},indent=2))
    if not args.dry_run and state['final_seed_results_observed'] and any(x['action']=='run_stage_script' for x in plan):raise RuntimeError('refusing mutation after final-seed lock; use verified outputs')
if __name__=='__main__':main()
