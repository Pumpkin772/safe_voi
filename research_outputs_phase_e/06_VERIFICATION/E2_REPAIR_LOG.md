# E2 preregistered repair log

Attempt 1 used the delayed discrete LQI as the nominal nonlinear controller.  Its unsaturated linear spectral radius passed, but 4 s control produced a persistent slow limit cycle for 0.05 and 0.08 pu steps (terminal absolute frequency 0.661 and 0.681 Hz).  This was a physical Gate failure, not removed data.  The original JSON, trajectory parquet, and log are retained as `FAILED_ATTEMPT_1_LQI_LIMIT_CYCLE.*` and `run_e2_rebuild_attempt1.log`.

The allowed first repair replaced the nominal upper controller with an ACE PI selected solely from the exact delayed-ZOH development model, with explicit back-calculation anti-windup.  No success threshold or disturbance magnitude changed.  The full matrix was rerun and passed.  LQI remains a candidate baseline only; it is not represented as the validated nominal loop.
