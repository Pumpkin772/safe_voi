"""Frozen Phase C experiment protocol and seed firewall."""
from __future__ import annotations
from dataclasses import dataclass

DEVELOPMENT_SEEDS=tuple(range(0,20));VALIDATION_SEEDS=tuple(range(100,120));FINAL_KNOWN_SEEDS=tuple(range(1000,1030));FINAL_OOD_SEEDS=tuple(range(2000,2050))
METHODS=('sg_only_pi','fixed_allocation','nominal_mpc','rls_adaptive_mpc','robust_capability_set_mpc','proposed_set_adaptive_mpc','O2_current_capability_nmpc','O3_clairvoyant_ceiling')
FAILURE_CLASSES=('success','physical_limit_failure','frequency_or_ace_failure','solver_failure','estimator_failure','code_failure','not_evaluated','not_applicable')
KNOWN_SCENARIOS=('nominal','headroom','ramp','delay','energy_low','service_disabled')
OOD_SCENARIOS=('asymmetric','compound_headroom_delay','gradual_drift','unknown_three_stage','current_limit_q','multiple_switches')

def assert_tuning_seeds(seeds):
    forbidden=set(FINAL_KNOWN_SEEDS)|set(FINAL_OOD_SEEDS)
    if forbidden.intersection(map(int,seeds)):raise RuntimeError('final seeds are forbidden for tuning')

def scenario_for_seed(seed:int,ood:bool=False)->str:
    choices=OOD_SCENARIOS if ood else KNOWN_SCENARIOS
    return choices[int(seed)%len(choices)]

def classify(*,code=False,solver=False,estimator=False,physical=False,performance=False,evaluated=True,applicable=True):
    if not applicable:return 'not_applicable'
    if not evaluated:return 'not_evaluated'
    if code:return 'code_failure'
    if solver:return 'solver_failure'
    if estimator:return 'estimator_failure'
    if physical:return 'physical_limit_failure'
    if performance:return 'frequency_or_ace_failure'
    return 'success'
