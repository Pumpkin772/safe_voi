# E3 materiality report

Best deployable baseline (success-first, then mean matched cost): **fixed_allocation_pi**.  O2 mean update solver success is 99.49%; successful-solve residual P99 is 2.233e-07.  22 episodes contain at least one failed solve; they remain in the episode table and are assessed by the separate solver-success/fallback Gate rather than being silently removed.  15 mechanism/tension cells satisfy the preregistered materiality rule.  Plant-B paired direction is consistent.

G3 result: **PASS**.  Continuous improvements are ratios of aggregate paired means, with seed-cluster bootstrap intervals; no mean of episode-wise relative ratios is used.  Failures, fallback episodes, and no-load negative controls remain in the episode table.
