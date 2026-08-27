# Prior-ambiguity and information-lifetime value boundary

## 1. Robust physical safety

For every retained capability hypothesis and disturbance realization, every
candidate information-producing action must satisfy

\[
x_k(\theta,w)\in\mathcal X,
\qquad
u_k(\theta,w)\in\mathcal U,
\qquad
\forall\theta\in\Theta,\;w\in\mathcal W.
\]

This condition is independent of the capability prior used to value
performance. A prior never relaxes power, ramp, delay, energy, SG, frequency,
ACE, or tie-line safety limits.

## 2. Branchwise paired control value

Let \(\xi\) denote a future event drawn from the registered event distribution.
For capability branch \(\theta\), define

\[
\Delta_\theta(q,T)
=
\mathbb E_\xi
\left[
J_c(\theta,\xi)
-J_q(\theta,\xi;T)
\right],
\]

where \(J_c\) is contract-MPC cost and \(J_q\) contains the full closed-loop
information-acquisition action, posterior update, and recourse until expiry.
Positive \(\Delta_\theta\) means the information strategy improves that
capability branch.

## 3. Explicit prior boundary

For binary low/high capability and \(p=P(H)\),

\[
V(q,p,T)
=(1-p)\Delta_L(q,T)+p\Delta_H(q,T).
\]

When \(\Delta_H>\Delta_L\), the analytic break-even probability is

\[
p^*(q,T)
=
\frac{-\Delta_L(q,T)}
{\Delta_H(q,T)-\Delta_L(q,T)}.
\]

The action has positive expected value only for \(p>p^*\). The study reports
the complete curve over \(p\in[0,1]\); it does not select a uniform prior as a
paper result.

For a prior ambiguity interval \(\Pi=[\underline p,\overline p]\),

\[
\underline V_\Pi(q,T)
=
\inf_{p\in\Pi}V(q,p,T).
\]

A prior-ambiguity positive region requires

\[
\underline V_\Pi(q,T)>0.
\]

An external fleet or service record may later locate a prior interval on this
map. Development does not alter \(\Pi\) after seeing method performance.

## 4. Immediate control and pure information value

Three paired controllers are required:

1. contract MPC, \(u_c\);
2. exploit-only control-aligned surplus, \(u_e\), with no posterior use;
3. dual control-aligned surplus, \(u_d\), with causal certification and
   posterior recourse.

The total value decomposes as

\[
V_{\rm control}=J(u_c)-J(u_e),
\]

\[
V_{\rm info}=J(u_e)-J(u_d),
\]

\[
V_{\rm total}=V_{\rm control}+V_{\rm info}.
\]

If \(V_{\rm info}=0\), the action is useful control with an informative side
effect, not a positive active-information result.

## 5. Evidence time and expiry

Let \(t_0\) be the first sample entering the capability evidence set and
\(T_{\rm valid}\) the registered persistence horizon. The hard expiry is

\[
t_{\rm expiry}=t_0+T_{\rm valid}.
\]

If certification needs \(T_{\rm cert}\) seconds after \(t_0\), useful recourse
time is

\[
T_{\rm useful}
=
\max(0,T_{\rm valid}-T_{\rm cert}).
\]

The validity clock is not restarted at certification. On expiry the online
performance envelope is removed and the controller returns to its contract-safe
set.

## 6. Correlated stacked actual-POI evidence

For a stacked causal actual-POI vector \(Y\), low/high mean responses
\(\mu_L,\mu_H\), and development covariance \(\Sigma\), define

\[
D^2
=(\mu_H-\mu_L)^\top
\Sigma^{-1}
(\mu_H-\mu_L).
\]

Gaussian classification error

\[
P_e\approx\Phi(-D/2)
\]

is a development diagnostic. The final outer capability set must also retain
the measured residual bound. A one-percent false-optimism limit is enforced on
independent development and validation realizations.

For an initial AR(1) sensitivity with window correlation \(\rho\),

\[
N_{\rm eff}
\approx
N\frac{1-\rho}{1+\rho}.
\]

Final certification time uses the stacked covariance calculation, not an
independent-window \(\sqrt N\) assertion.

## 7. Low-capability downside

The low branch remains physically safe for every action. In addition, the
registered performance downside must satisfy

\[
\Delta f_{\rm peak,L}\le0.005\;\mathrm{Hz},
\]

\[
\frac{J_{\rm ACE,L}^{q}-J_{\rm ACE,L}^{c}}
{J_{\rm ACE,L}^{c}}
\le1\%,
\qquad
\frac{J_{\rm tie,L}^{q}-J_{\rm tie,L}^{c}}
{J_{\rm tie,L}^{c}}
\le1\%.
\]

This prevents a high-capability prior from hiding a materially adverse low
branch.

## 8. Grid-service and resource-price boundary

The physical grid-service cost is frozen before validation as

\[
J_{\rm grid}
=\int\left[
\sum_{i=1}^{2}\left(\frac{\Delta f_i}{0.20\ {\rm Hz}}\right)^2
+\sum_{i=1}^{2}\left(\frac{{\rm ACE}_i}{0.05\ {\rm pu}}\right)^2
+\left(\frac{P_{\rm tie}}{0.025\ {\rm pu}}\right)^2
\right]dt.
\]

Frequency, ACE, and tie-line quality therefore all have nonzero, physically
stated scales.  SG mechanical mileage and BESS energy throughput are not hidden
inside optimizer smoothing penalties.  Paired value is retained in three
coordinates,

\[
(\Delta J_{\rm grid},\Delta M_{\rm SG},\Delta E_{\rm BESS}),
\]

and priced value is

\[
V(c_g,c_b)
=\Delta J_{\rm grid}
+c_g\Delta M_{\rm SG}
+c_b\Delta E_{\rm BESS},
\qquad c_g,c_b\ge0.
\]

The paper reports the complete nonnegative resource-price half-space rather
than choosing an unreferenced SG/BESS price after seeing results.  A positive
claim requires an interior prior--price rectangle whose paired confidence
lower bound remains positive after the rectangle is frozen and rerun on
independent seeds.  Pareto-dominated actions are classified as no-probe without
reference to any price.

## 9. Selective amplitude and mechanism

For each causal state, prior interval, and validity horizon, the selected
information action is

\[
q^*
=
\arg\max_{q\in\mathcal Q_{\rm safe}}
\underline V_\Pi(q,T_{\rm valid})
\]

subject to the false-optimism, expiry, and low-branch downside limits. If the
maximum is nonpositive, the exact action is contract MPC.

The development factorial compares

\[
T_{\rm valid}\in\{24,240\}\;\mathrm{s},
\]

scalar versus vector observation, and allocation-neutral versus
control-aligned acquisition. For every cell the complete \(V(p)\) and \(p^*\)
are reported.

Futility is not declared from one noisy delivery sample. Development target-
distribution runs showed that a single sample can fall below the contract
margin even in a true high-capability branch because of delay and measurement
noise. At least two causal samples are required before stopping a second
information window; this rule is frozen before validation.

## 10. Current evidence status

Across six paired nonlinear development seeds, the adaptive 0.003--0.004 pu
control-aligned action established positive pure information ACE value in all
six high-capability episodes and zero false certification in all six low-
capability episodes.  Mean total ACE and tie values relative to contract MPC
were positive in the high branch, while total SG movement and BESS throughput
increased.  The pilot therefore establishes a candidate information mechanism,
not a paper result.

Before a positive prior-ambiguity region can be declared, the registered
multi-metric physical cost must explicitly price the resource tradeoff and the
candidate must be rerun on the 480 s independent capability/load-event
distribution.  The six-seed pilot used a fixed 300 s screening episode, so its
positive values cannot be substituted for independent validation evidence.
