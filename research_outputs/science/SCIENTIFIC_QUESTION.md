# Phase C Scientific Question

## Locked question

When a black-box IBR/BESS participating in multi-area secondary frequency control undergoes an unannounced change in its externally available upward/downward power headroom, ramp capability, command latency, sustainable energy, or service availability, can a control centre use only externally measurable input/output data to recognize the control-relevant capability change before a stale capability model causes material frequency, ACE, tie-line, or physical-constraint harm, and then safely reallocate regulation responsibility?

## Deployment boundary

The deployable controller may use measured area frequency, ACE, tie-line exchange, SG mechanical power, IBR POI active power, issued SG/IBR commands and their histories. It may use a state/load estimator whose inputs are those same measurements. It may not read the simulator's true capability regime, hidden parameters, unmeasured true SoC, true load disturbance, future load, future capability events, or future packet delivery.

The evaluation-only O1/O2/O3 hierarchy may use explicitly declared truth information solely to estimate an upper bound. Oracle rows are never pooled with deployable-controller rows as if their information sets were equal.

## Control-relevant object

The object of inference is a capability vector or set

\[
c=[P^+,P^-,R^+,R^-,\tau,T_c,T_p,E^{avail},a,\eta]^\top,
\]

not an OEM label. Two labeled states are merged when their reachable POI responses, feasible control sets, and optimal regulation actions are equivalent over the admissible input/disturbance set. A single OEM label may split when its operating-point capability changes enough to alter those quantities.

## Inputs, hidden quantities and outputs

- Manipulated variables: 2/4 s zero-order-held SG SFR and IBR SFR commands in both areas.
- Fixed local service: SG droop and IBR PFR; these are not optimized by the proposed upper layer.
- Hidden quantities: capability vector, actual service availability, internal command delay/filter state, unmeasured energy/SoC, future events and true net-load disturbance.
- Evaluation outputs: frequency and RoCoF in Hz units, ACE, tie-line interchange, SG/IBR power and energy, resource violations, solver/estimator status, capability-set coverage, `Tdet`, and `Tcrit`.

## Falsifiability

The question fails materially if, after corrected-unit Plant A/Plant B validation and a fair rolling no-future-information NMPC Oracle qualification, true current-capability knowledge has no preregistered control value in both plants. It fails as a passive-diagnosis claim if `P(Tdet<Tcrit)<0.8` or false alarms exceed 5%. It fails as a universal-identification claim if allowed safe inputs cannot distinguish capability candidates. Those outcomes trigger the predefined negative or robust-control branch; they do not authorize changing thresholds.

## Locked scope

The work studies positive-sequence RMS/DAE secondary frequency regulation with an average-value IBR/BESS capability model. It does not claim OEM source-code recovery, EMT-complete validation, universal nonlinear stability, or novelty from mode classification alone.
