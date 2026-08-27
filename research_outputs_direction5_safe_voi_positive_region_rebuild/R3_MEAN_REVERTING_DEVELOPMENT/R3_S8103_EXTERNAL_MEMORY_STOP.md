# Seed 8103 first attempt: external system-memory stop

The first contract attempt for the fixed 4 s replication seed 8103 was
terminated after 97.484 s because total Windows committed memory reached
0.92227 of the system limit, above the retained 0.92 stop threshold.  The
Direction5 process tree itself peaked at only 458,690,560 bytes and one child
process.

Inspection after termination found 15 Python training processes from a
different `peee-py311` research task, not this repository.  They were not
terminated or modified.  When that external workload later fell to three
processes, free virtual memory rose from 6.19 GiB to 17.44 GiB.  The same seed
and scientific configuration may then be rerun under the unchanged memory
limits.  No scientific episode result was written by the stopped attempt.

## Seed 8104 contract stop

The first seed 8104 contract attempt was likewise stopped before producing an
episode result.  It ran for 166.984 s; total system commit briefly reached
0.96562 while the Direction5 tree used only 445,894,656 bytes.  The coincident
external workload contained a 200-episode RSR-MASAC process and an independent
information-aligned MPC tuning process with four `multiprocessing.spawn`
workers.  The Direction5 0.92 limit was not raised.  Seed 8104 remains pending
with its scientific configuration unchanged.
