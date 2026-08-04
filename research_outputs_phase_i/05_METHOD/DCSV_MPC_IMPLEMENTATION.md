# Final rolling DCSV-MPC implementation

Every control call constructs and solves a finite-horizon QP with a common SG/
BESS control sequence, one predicted state and measured-energy sequence per
contract-delay vertex, discrete grid dynamics, actual-action delay pipeline,
power/ramp/energy/valve/mechanical limits, slow-reserve state and request
sequences, and sustainable-terminal or bridge-progress conditions. Hard limits
use only the contract. Online deliverability changes a revocable performance
weight, never a hard constraint. The ordinary input contains causal observations,
load estimate, deliverability set, measured SoC, domain decision and violation
status; no truth or future field exists.
