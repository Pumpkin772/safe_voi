"""Assemble and verify the strict Phase C 00--14 review ZIP."""
from __future__ import annotations
import csv,hashlib,json,os,platform,shutil,subprocess,sys,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];STAGE=ROOT/'artifacts_phase_c'/'final_review_package';ZIP=ROOT/'DIRECTION5_PHASE_C_FULL_REBUILD_AND_METHOD_COMPLETION_SINGLE_REVIEW_PACKAGE.zip'
DIRS=['00_README','01_SCIENCE','02_LITERATURE','03_MODEL_AND_THEORY','04_SOURCE','05_CONFIG_AND_ENV','06_TESTS_AND_VERIFICATION','07_EXPERIMENT_DESIGN','08_RAW_RESULTS','09_SUMMARY_TABLES','10_FIGURES','11_FAILURES','12_REPRODUCIBILITY','13_GIT_AND_MANIFEST','14_FINAL_STATUS']
def cp(src,dst):
    src=ROOT/src if not Path(src).is_absolute() else Path(src);dst=STAGE/dst;dst.parent.mkdir(parents=True,exist_ok=True)
    if src.is_dir():shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','*.pyc','.git'))
    elif src.exists():shutil.copy2(src,dst)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    if STAGE.exists():shutil.rmtree(STAGE)
    for d in DIRS:(STAGE/d).mkdir(parents=True)
    # Required named files.
    for f in ('README_FIRST.md','HOW_TO_REVIEW.md'):cp('research_outputs/final/'+f,'00_README/'+f)
    for f in ('SCIENTIFIC_QUESTION.md','HYPOTHESES_AND_FALSIFICATION.md','SUPPORTED_AND_UNSUPPORTED_CLAIMS.md'):cp('research_outputs/science/'+f,'01_SCIENCE/'+f)
    gates={f'C{i}':json.loads((ROOT/f'progress/C{i}_gate_decision.json').read_text()) for i in range(9)};(STAGE/'01_SCIENCE/SCIENCE_GATE_DECISIONS.json').write_text(json.dumps(gates,indent=2),encoding='utf-8');cp('progress/decision_ledger.md','01_SCIENCE/decision_ledger.md')
    for f in ('LITERATURE_REVIEW.md','LITERATURE_MATRIX.csv','NOVELTY_COMPARISON_TABLE.md','SOURCE_BIBLIOGRAPHY.bib','SEARCH_LOG.md'):cp('research_outputs/literature/'+f,'02_LITERATURE/'+f)
    for f in ('FULL_MATHEMATICAL_MODEL.md','FORMULA_CODE_MAP.csv','PARAMETER_SOURCES.csv','ASSUMPTIONS_AND_LIMITATIONS.md'):cp('research_outputs/model/'+f,'03_MODEL_AND_THEORY/'+f)
    cp('research_outputs/method/THEORY_AND_PROOFS.md','03_MODEL_AND_THEORY/THEOREMS_AND_PROOFS.md');cp('research_outputs/model/NUMERICAL_CERTIFICATE_INDEX.csv','03_MODEL_AND_THEORY/NUMERICAL_CERTIFICATE_INDEX.csv')
    for d in ('src','scripts','tests'):cp(d,'04_SOURCE/'+d)
    cp('configs','05_CONFIG_AND_ENV/configs');cp('environment.yml','05_CONFIG_AND_ENV/environment.yml');cp('pyproject.toml','05_CONFIG_AND_ENV/pyproject.toml')
    freeze=subprocess.run([sys.executable,'-m','pip','freeze'],capture_output=True,text=True,check=True).stdout;(STAGE/'05_CONFIG_AND_ENV/requirements-lock.txt').write_text(freeze,encoding='utf-8')
    env={'python':sys.version,'platform':platform.platform(),'processor':platform.processor(),'andes':'2.0.0','casadi':'3.7.2','licenses_packaged':False};(STAGE/'05_CONFIG_AND_ENV/environment.json').write_text(json.dumps(env,indent=2),encoding='utf-8')
    cp('results_phase_c/C2','06_TESTS_AND_VERIFICATION/C2');cp('results_phase_c/C3','06_TESTS_AND_VERIFICATION/C3');cp('logs_phase_c/C0','06_TESTS_AND_VERIFICATION/C0_logs');cp('logs_phase_c/C2','06_TESTS_AND_VERIFICATION/C2_logs');cp('logs_phase_c/C9','06_TESTS_AND_VERIFICATION/C9_full_tests')
    cp('research_outputs/experiment','07_EXPERIMENT_DESIGN');cp('results_phase_c/C7/LOCKED_HASHES.json','07_EXPERIMENT_DESIGN/FINAL_PROTOCOL_LOCK.json');cp('research_outputs/experiment/SCENARIO_MANIFEST.csv','07_EXPERIMENT_DESIGN/EXPERIMENT_MATRIX.csv');cp('research/phase_c_full_rebuild_and_method_completion','00_README/governing_phase_c_spec')
    cp('results_phase_c','08_RAW_RESULTS');cp('logs_phase_c','08_RAW_RESULTS/logs')
    for f in ('summary_table.csv','success_first_four_cell.csv','scene_balanced_summary.csv','final_analysis.json','cost_sensitivity.csv','ablation_status.csv','method_summary.csv'):cp('results_phase_c/C8/'+f,'09_SUMMARY_TABLES/'+f)
    cp('results_phase_c/C4/materiality_summary.json','09_SUMMARY_TABLES/materiality_summary.json');cp('results_phase_c/C5/identifiability_summary.json','09_SUMMARY_TABLES/identifiability_summary.json')
    cp('figures_phase_c','10_FIGURES/figures_phase_c');cp('scripts/phase_c/c8_reporting.py','10_FIGURES/generation/c8_reporting.py')
    cp('results_phase_c/C8/failure_ledger.csv','11_FAILURES/FAILURE_LEDGER.csv');cp('results_phase_c/C8/solver_failures.csv','11_FAILURES/SOLVER_FAILURES.csv');cp('research_outputs/results/WORST_CASES.md','11_FAILURES/WORST_CASES.md');cp('research_outputs/results/NEGATIVE_RESULTS.md','11_FAILURES/NEGATIVE_RESULTS.md');cp('progress/REPAIR_LEDGER.md','11_FAILURES/REPAIR_LEDGER.md')
    cp('research_outputs/reproducibility/RUN_ALL.md','12_REPRODUCIBILITY/RUN_ALL.md');
    for f in ('reproduce_minimal.ps1','reproduce_all.ps1','regenerate_figures.ps1'):cp('scripts/phase_c/'+f,'12_REPRODUCIBILITY/'+f)
    for f in ('FINAL_RESEARCH_STATUS.md','FINAL_DECISION.json','PAPER_OUTLINE.md','RESULTS_INTERPRETATION.md','NEXT_UNRESOLVED_RISKS.md','DATA_RETENTION_POLICY.md'):cp('research_outputs/final/'+f,'14_FINAL_STATUS/'+f)
    git={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),'status':subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True)};(STAGE/'13_GIT_AND_MANIFEST/GIT_STATE.json').write_text(json.dumps(git,indent=2),encoding='utf-8')
    # File manifest and package index are generated last.
    rows=[]
    for p in sorted(STAGE.rglob('*')):
        if p.is_file():rows.append({'path':p.relative_to(STAGE).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
    for target in (STAGE/'13_GIT_AND_MANIFEST/FILE_MANIFEST.csv',STAGE/'00_README/PACKAGE_INDEX.csv'):
        with target.open('w',newline='',encoding='utf-8') as f:w=csv.DictWriter(f,fieldnames=['path','bytes','sha256']);w.writeheader();w.writerows(rows)
    if ZIP.exists():ZIP.unlink()
    with zipfile.ZipFile(ZIP,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(STAGE.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(STAGE).as_posix())
    with zipfile.ZipFile(ZIP) as z:
        bad=z.testzip();members=z.namelist();tops={m.split('/')[0] for m in members}
    result={'zip':str(ZIP),'bytes':ZIP.stat().st_size,'sha256':sha(ZIP),'members':len(members),'crc_error':bad,'required_directories_present':all(d in tops for d in DIRS),'under_512mb':ZIP.stat().st_size<512*1024*1024}
    (ROOT/'artifacts_phase_c'/'FINAL_ZIP_VERIFICATION.json').write_text(json.dumps(result,indent=2),encoding='utf-8');(ROOT/(ZIP.name+'.sha256')).write_text(result['sha256']+'  '+ZIP.name+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
