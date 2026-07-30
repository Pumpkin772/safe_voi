# Phase E governance reading acknowledgement

Date: 2026-07-31

Governing goal: `research/direction1_phase_e_science_recovery_and_capability_control/CODEX_GOAL.md`

Project name: `DIRECTION1`

## Files read completely

1. `README_FIRST.md`
2. `00_CURRENT_PACKAGE_EXPERT_REVIEW.md`
3. `01_MASTER_EXECUTION_PLAN.md`
4. `02_CORRECTED_SCIENTIFIC_QUESTION_AND_HYPOTHESES.md`
5. `03_MODEL_AND_BASELINE_REBUILD_SPEC.md`
6. `04_ORACLE_MATERIALITY_AND_CAUSAL_INFORMATION_PROTOCOL.md`
7. `05_PASSIVE_AND_ACTIVE_CAPABILITY_IDENTIFICATION_SPEC.md`
8. `06_FINAL_METHOD_BRANCH_SPEC.md`
9. `07_THEORY_AND_PROOFS_SPEC.md`
10. `08_EXPERIMENT_AND_STATISTICS_PROTOCOL.md`
11. `09_SOFTWARE_ARCHITECTURE_AND_STAGE_CONTRACTS.md`
12. `10_GATES_FAILURE_AND_AUTO_REPAIR.md`
13. `11_FINAL_REVIEW_PACKAGE_SPEC.md`
14. `CODEX_GOAL.md`
15. `GOAL_TO_SEND_CODEX.txt`
16. `reference/config_template.yaml`
17. `reference/independent_audit_expected_output.json`
18. `reference/independent_audit_reproduction.py`
19. `reference/LITERATURE_ANCHORS.md`
20. `reference/REFERENCE_FINDINGS.json`

The directory contained 20 files. Before execution, every file was inventoried with byte size and SHA256 and read in full as UTF-8.

## Decisive Phase D defects understood

- The registered 2 s, `Kp=1.4`, `Ki=0.18`, 35/65 PI loop self-excites and saturates; the old natural-I/O experiment is not representative stable AGC operation.
- The delay candidate set can change and recover the true singleton without a CUSUM alarm, while the Phase D evaluator records `update_time` only on alarms.
- The old `control_loss_time` is a command-output deficit-area threshold, not an actual frequency/ACE/tie/constraint or matched Oracle counterfactual control loss.
- When all three development candidates fail, Phase D selects the last candidate rather than a preregistered Pareto/minimum-violation candidate; this selected the worst coverage candidate.
- Phase D applied H2 before establishing H1 materiality, omitted real energy/availability changes and Plant B identification evidence, and therefore cannot support a general passive-identifiability conclusion.

The former conclusion is withdrawn and replaced by:

`PHASE_D_GATE_INVALIDATED_BY_CLOSED_LOOP_AND_EVALUATION_DEFECTS`

## Locked execution order

`E0 → E1 → E2 → E3 → E4 → E5 (only if required) → E6 → E7 → E8 → E9`

Materiality precedes identification. If G4 passes, select P and skip E5. If G4 fails after G3 passes, evaluate E5; select A only if G5 passes, otherwise select R. Only one selected branch may be implemented and final-tested.

## Fatal/negative stopping conditions

- `FATAL_BASELINE_INCOMPLETE`
- `NOVELTY_NOT_SUPPORTED`
- `FATAL_PHYSICAL_OR_CLOSED_LOOP_MODEL_FAILURE`
- `PROBLEM_NOT_MATERIAL`
- `METHOD_NOT_SUPPORTED_BY_EVIDENCE`
- `FINAL_EVIDENCE_NOT_SUPPORTED`

A scientific/fatal stop still proceeds to E9 with a complete negative package. Failed episodes are retained, solver failures remain distinct from `not_evaluated`, and final seeds cannot be used for tuning.

## Information boundary

Deployable estimators/controllers may use only public frequency, ACE, tie-line, SG/BESS power and command histories plus causal estimates. They may not read true capability/regime, hidden parameters/state, true load, future events, or Oracle outputs. O2 Oracle truth access is confined to the evaluation namespace and includes current, never future, capability/state information.

## Final deliverable

`DIRECTION1_PHASE_E_SCIENCE_RECOVERY_AND_CAPABILITY_CONTROL_SINGLE_REVIEW_PACKAGE.zip`, strictly following the 00–16 layout in `11_FINAL_REVIEW_PACKAGE_SPEC.md`, smaller than 512 MB, with complete hashes, raw evidence, failures, reproducibility, Git state and final H1–H5/branch decisions.
