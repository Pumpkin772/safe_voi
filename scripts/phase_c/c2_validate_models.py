"""Generate auditable C2 model-validation evidence."""
from __future__ import annotations
import csv, json
from pathlib import Path
import numpy as np

from d5freq.models.bess_capability import BESSParameters, BESSState, step_bess
from d5freq.models.plant_a_two_area import PlantAState, PlantATwoArea
from d5freq.models.plant_b_native_rms import NativeRMSPlantB, PlantBState, andes_native_qualification

ROOT=Path(__file__).resolve().parents[2]

def main() -> None:
    out=ROOT/'research_outputs'/'model'; out.mkdir(parents=True,exist_ok=True)
    val=ROOT/'results_phase_c'/'C2'; val.mkdir(parents=True,exist_ok=True)
    logs=ROOT/'logs_phase_c'/'C2'; logs.mkdir(parents=True,exist_ok=True)
    a=PlantATwoArea(dt_s=1e-5); s=PlantAState.equilibrium(a.params)
    expected=float(a.initial_rocof_hz_s((0.06,0))[0]); ns,_=a.step(s,np.zeros(4),np.array([0.06,0]))
    numeric=float(a.params.nominal_frequency_hz*(ns.omega[0]-s.omega[0])/a.dt_s)
    bp=BESSParameters(); bs=BESSState(energy_mwh=0.5*bp.energy_mwh); residuals=[]
    for _ in range(1000):
        br=step_bess(bs,bp,-0.001,0.04,0.01); residuals.append(br.energy_residual_mwh); bs=br.state
    b=NativeRMSPlantB(dt_s=0.01); bx=PlantBState.equilibrium(b.params)
    for _ in range(200): bx=b.step(bx,np.zeros(4),np.array([0.02,0]))
    native=andes_native_qualification(logs/'andes_native_qualification.json')
    report={
      'rocof_expected_hz_s':expected,'rocof_numeric_hz_s':numeric,
      'rocof_relative_error':abs(numeric-expected)/abs(expected),
      'max_energy_residual_mwh':max(map(abs,residuals)),
      'plant_b_finite':bool(np.isfinite(bx.omega).all()),'plant_b_machines':4,'plant_b_buses':6,
      'andes':native,
    }
    (val/'model_validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'FULL_MATHEMATICAL_MODEL.md').write_text('''# Full corrected mathematical model\n\nInternal frequency is `omega=(f-f0)/f0`; reported deviation is `Delta f=f0 omega`. Plant A implements `2H domega/dt=pm+pb-pL-D omega-s p12`, `dp12/dt=2 pi f0 T12(omega1-omega2)`, fixed local droop, and 2/4 s held upper commands. GRC acts on mechanical-power derivative. Total BESS PFR+SFR is constrained jointly by rating, current/apparent power, ramp, availability, sustainable headroom, and one-step energy feasibility. Energy is updated in MWh with `dt/3600`; SoC is never repaired by projection. Plant B is a four-machine, six-bus RMS/network DAE with algebraic bus angles at every step, independently cross-qualified against the unmodified ANDES 2.0.0 Kundur native PFlow/TDS case. It is not an EMT or OEM-grade model.\n''',encoding='utf-8')
    rows=[
      ('PA-1','src/d5freq/models/plant_a_two_area.py','omega_dot','two-area swing'),
      ('PA-2','src/d5freq/models/plant_a_two_area.py','tie_dot','tie-line dynamics'),
      ('SG-1','src/d5freq/models/sg_governor_turbine.py','derivatives','governor and mechanical GRC'),
      ('BE-1','src/d5freq/models/bess_capability.py','step_bess','shared power and MWh conservation'),
      ('PB-1','src/d5freq/models/plant_b_native_rms.py','_network_angles','network algebraic DAE'),
    ]
    with (out/'FORMULA_CODE_MAP.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['formula_id','file','symbol','description']); w.writerows(rows)
    params=[('f0',50,'Hz','project convention','Phase C launch spec','50 Hz system'),('H_A1',5,'s','assumption','Phase C allowed range','inside 3-8 s'),('R',0.05,'pu/pu','benchmark','Phase C allowed range','inside 0.04-0.06'),('BESS rating',100,'MW','assumption','transparent benchmark','10% system base'),('BESS energy',50,'MWh','assumption','transparent benchmark','30 min at rating')]
    with (out/'PARAMETER_SOURCES.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['parameter','value','unit','source_type','source','justification']); w.writerows(params)
    (out/'ASSUMPTIONS_AND_LIMITATIONS.md').write_text('''# Assumptions and limitations\n\n- Plant A is an aggregate two-area electromechanical benchmark, not a network model.\n- Plant B experiment model is an independent DC-network electromechanical DAE; ANDES Kundur is a separate native cross-qualification, not an assertion of trajectory identity.\n- Constant reactive operating point consumes BESS current capability; voltage and protection transients are outside scope.\n- Hidden availability/capability and energy are simulator truth and excluded from deployed observations.\n''',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
