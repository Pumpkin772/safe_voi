# Locked statistical analysis plan

"
        "The fatal H2 Gate precedes controller/Oracle evaluation. Therefore no H1, H3, H4, "
        "known/OOD, ablation, Pareto, or controller success-first comparison is computed. "
        "Those cells remain `not_evaluated`, never method failures.

"
        "For the completed D3 experiment, report joint and marginal truth coverage, false and "
        "pre-change alarm rates, per-mechanism update-before-loss probability, and the exact "
        "numbers of timing-evaluated versus not-applicable episodes. No mean episode-wise "
        "relative percentages are used. All development rounds and validation failures remain.
",
        encoding="utf-8",
    )
    (REPORTS / "METRIC_DICTIONARY.csv").write_text(
        "metric,unit,aggregation,interpretation
"
        "joint_coverage,fraction,time-weighted_then_episode-balanced,truth inside all capability intervals
"
        "power_coverage,fraction,time-weighted_then_episode-balanced,truth inside power interval
"
        "ramp_coverage,fraction,time-weighted_then_episode-balanced,truth inside ramp interval
"
        "delay_coverage,fraction,time-weighted_then_episode-balanced,truth inside delay interval
"
        "energy_coverage,fraction,time-weighted_then_episode-balanced,truth inside energy interval
"
        "false_alarm_rate,fraction,scenario-balanced,no-change episode with an alarm
"
        "prechange_alarm_rate,fraction,scenario-balanced,alarm before physical change
"
        "update_before_control_loss,fraction,mechanism-balanced,causal update precedes registered loss time
",
        encoding="utf-8",
    )
    (REPORTS / "COMPUTE_BUDGET.md").write_text(
        D0-D2 verification and D3 development/validation were completed locally on Windows with four worker processes for D3. The planned final matrix contains 2,400 scenarios per controller, but zero final controller episodes were run because H2 is a fatal scientific Gate. Running them would violate the automatic-stop contract.
