# Data retention policy

All 120 D3 validation episode metrics, all 55 episode-level capability-set failures, all three development candidates, update-timing records, and structural non-identifiability cases are retained. No failed episode was deleted.

D3 is an estimator Gate before any Direction1 MPC/controller exists. Consequently there are no post-D3 controller-cycle trajectories to retain. The archive stores fine-step causal traces for one deterministic representative seed in each of the ten D3 scenario families, including the worst retained failure. The remaining D3 episodes are deterministically regenerated from the scenario definition and recorded development/validation seeds. All 2,400 planned final controller scenarios remain in the D7 manifest as `not_evaluated`; no synthetic trajectories are created for them.

Parquet files use Zstandard compression. Statistical summaries remain float64; stored time-series variables use their source precision because the D3 evidence is small and preserving exact threshold reconstruction is more important than an immaterial size reduction.
