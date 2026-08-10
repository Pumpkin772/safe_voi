# A0 resource incident and mandatory repair

## Incident

The first A0 launcher combined a three-worker `ProcessPoolExecutor` with a
subsequent native ANDES initialization in the parent process. ANDES detected
generated code that it considered stale and launched approximately 18
`multiprocess.spawn` workers. System committed memory reached
127.42/127.43 GiB, `dwm.exe` repeatedly crashed, and the desktop blacked out.
The run was terminated and must not be replayed with the unsafe launcher.

## Corrective controls

1. A0 is strictly sequential; values of `--workers` other than `1` are refused.
2. Native Plant B runs in an isolated process after Plant A, never inside or
   after a reusable Python process pool.
3. ANDES automatic code generation is fail-closed. Missing, incomplete, or
   unimportable generated code produces an explicit error before codegen can
   create child processes.
4. Direct unguarded A0 and native ANDES execution are refused.
5. The supported launcher is `scripts/direction5_accr/run_a0_guarded.py`.
6. On Windows, a Job Object limits the guarded tree to three total processes
   (A0, its automatically attached `conhost.exe`, and at most one Plant-B
   worker), caps committed job memory at 4 GiB, and kills the tree if the guard
   exits. A first codegen child would be the fourth process and is refused.
7. A 100 ms monitor records system commit, commit growth, available physical
   memory, process-tree RSS/private bytes, descendant count, and elapsed time.
   It stops the complete tree on any registered breach.

No simulation was launched while implementing this repair. Existing A0 output
is retained but is not promoted to a formal Gate until the corrected guarded
workflow is explicitly authorized and independently verified.
