# B2 independent validation result

The frozen development boundary was evaluated twice with independent sampling
and independent nonlinear episode seeds. No weight, threshold, probe, design
range, or scenario definition was changed after the B1 lock.

## Independent boundary confirmation

| split | seed | points | direct zero | upper checked | positive upper | max PI value | max probe upper |
|---|---:|---:|---:|---:|---:|---:|---:|
| validation_1 | 7300 | 128 | 123 | 5 | 0 | 0.0029443313 | -0.0210039907 |
| validation_2 | 7400 | 128 | 120 | 8 | 0 | 0.0038456876 | -0.0190042617 |

The two splits used 2,421 optimization calls and had zero solver failures.
Both independently reproduce the empty registered positive-value region.

## Full nonlinear Plant A

- 40 independent 300 s scenarios: two 2 s cells and two 4 s cells, with 10
  seeds per cell and balanced known/OOD coverage.
- 37/40 met the registered terminal-recovery condition.
- All 40 had zero hard and command violations.
- The three retained failures were 2 s OOD area-1 persistent-imbalance cases;
  peak frequency remained below 0.429 Hz, but terminal ACE/frequency did not
  recover within the last 30 s.
- All issued zero probes and had exactly zero contract-action and core-metric
  difference. The contract and selective rows refer to one shared physical
  trajectory because the frozen scheduler returns the same contract action
  object when the map has no positive region.

## Native ANDES Plant B

- 12 independent 300 s native Kundur DAE scenarios: six 2 s known and six 4 s
  OOD repeats.
- 12/12 initialized and converged; maximum initialization residual was
  2.3093e-14 and maximum p99 algebraic balance residual was 1.8446e-8 pu.
- 12/12 were physically successful with zero hard/command violations.
- Maximum peak frequency deviation was 0.077381 Hz.
- All issued zero probes and were exactly contract-equivalent.

## Computation and interpretation

Across the 52 actually executed selective trajectories there were 5,902
rolling optimization calls, zero solver failures, and zero fallbacks. The
maximum individual solve time was 2.6514 s; hence the present Python/CVXPY
implementation does not establish the registered 2 s real-time requirement,
even though the physical and no-probe results are unaffected. Ordinary
controllers read no capability truth.

There were no optimistic certificates because no positive cell existed. The
false-optimistic-certificate count is zero, but a conditional empirical rate is
not estimated when the denominator is zero. Candidate-set reduction and Oracle
value recovery are not applicable: the selected action is to acquire no
capability information.

B2 therefore supports the boundary-negative branch. It does not support a
positive selective probing claim.
