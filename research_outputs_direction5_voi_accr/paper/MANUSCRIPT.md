# Value boundaries of information-gated active capability certification for black-box IBRs in multi-area frequency control

## Abstract

This study asks whether active certification of hidden inverter-based-resource power, ramp, and delay capability has positive net control value in multi-area secondary frequency control. We formulate VOI-ACCR-MPC, which places a zero-mean SG--IBR allocation probe around the current contract-MPC optimum only when a causal decision-relevance and value-of-information gate predicts positive net value. In low-value conditions it exactly abstains and reduces to contract MPC. A development prototype passed on eight nonlinear Plant-A cases, but a locked independent validation on 48 full nonlinear Plant-A and 12 native ANDES Plant-B paired scenarios did not validate the performance claim. In the preregistered worthwhile subset, scenario-balanced VOI improvements were -0.016% for ACE IAE and -0.053% for tie-line IAE, with confidence intervals spanning zero. Native Plant B triggered no probes. A separate perfect-capability screen at horizons 3, 4, and 6 found a best aggregate value of only 1.769% for tie-line IAE and 0.295% for ACE IAE, below the preregistered 4% materiality threshold. We therefore report a bounded decisive negative result: safe selective probing has a nonempty development region, but its net cross-plant control value is insufficient under the registered problem.

## 1. Scientific question

The ordinary controller observes frequency, ACE, tie-line flow, issued commands, actual BESS point-of-interconnection power, and measured SoC. It does not read true capability, true load, hidden parameters, or future events. The question is not whether a probe can distinguish candidate models in isolation, but whether the information changes a constrained recourse decision enough to repay the closed-loop frequency, ACE, tie-line, synchronous-generator-mileage, and energy costs of probing.

## 2. Method

VOI-ACCR-MPC maintains causal power/ramp/delay candidate models and separates the guaranteed contract floor from a conditional online envelope. The base command is the contract-MPC optimum. A two-step zero-mean allocation perturbation of amplitude 0.0025 pu is considered only when multiple candidates imply materially different optimal actions and predicted recourse benefit exceeds probe cost. A missing certificate never triggers a probe. Certificates expire after 4 s, use cooldown and change reset, and cannot authorize delivery below the contract floor. The selected M1 horizon is three control steps.

## 3. Protocol

M1 used eight 300 s full nonlinear Plant-A development scenarios covering power/ramp uncertainty and low/high SG tension. M2 used independent seeds and 60 paired scenarios: 48 full nonlinear Plant A and 12 native ANDES Plant B, crossing power/ramp/delay, 2/4 s control, known/OOD, SG tension, event timing, and 300--600 s duration. Contract-only rolling MPC is the primary baseline and perfect-capability rolling recourse MPC is evaluation-only. Two genuine 3600 s normal profiles and four contract-violation design cells were evaluated separately. Statistics use scenario-balanced aggregate means, paired absolute differences, and the registered hierarchical bootstrap.

## 4. Results

### 4.1 Development

M1 found four worthwhile and four not-worthwhile Plant-A cases. Tie-line IAE improved 3.776%, ACE IAE improved 1.374%, candidate diameter fell 50%, hard violations and fallbacks were zero, and low-value controls had zero probes and exact baseline performance. This result was used only to lock a prototype.

### 4.2 Independent validation

The M2 worthwhile subset contained 30 scenarios, of which 24 triggered probes. Aggregate ACE and tie-line improvements were -0.0163% and -0.0526%, respectively. SG mechanical mileage changed by -1.4807%. Mean diameter reduction over the preregistered worthwhile set was 35.00%, below the 50% Gate; over actually probed cases it was 43.75%. Four of 21 audited certificate issues were false optimistic. Plant A had a best primary improvement of -0.0328%; Plant B had zero VOI change because no probe was triggered, so cross-plant positive direction failed.

Safety and numerical gates were not the bottleneck: all 32043 attempted optimization calls are included in the denominator, with zero solver failures, restorations, or fallbacks and zero hard violations. Low-value controls had zero probes and exact metric equality. The real 3600 s normal profile had zero hard violations and a maximum frequency peak of 0.007273 Hz.

### 4.3 Post-validation diagnosis

The false optimistic certificates occurred when the load event preceded an unannounced capability transition. A grid-cell outer certificate and change-detection gate eliminated optimism only by abstaining in every new development scenario. A second independent development search over validity and VoI margin retained safe abstention but did not recover registered benefit. Perfect-capability horizon screening then bounded the remaining explanation: tie-line value decreased from 1.769% at horizon 3 to 1.570% at horizon 6, while ACE value remained below 0.295%.

## 5. Interpretation

The negative result is not a generic impossibility theorem for active capability identification. It shows that, for the registered plants, contract, uncertainty range, physical disturbance family, and rolling MPC, the controllable value available even to perfect capability information is below the paper-level threshold. A causal probe can only recover a fraction of this ceiling and must additionally pay excitation cost. Consequently, more aggressive or repeated probes cannot establish the preregistered aggregate claim without changing the scientific problem or lowering the Gate.

## 6. Limitations and bounded claims

The sample is finite, only the registered full nonlinear Plant A and native ANDES Plant B are studied, and the Oracle screen covers horizons 3, 4, and 6 rather than arbitrary horizons. The certificate guarantee is conditional on the enumerated candidate set and probe guard; the online certificate did not pass empirical validity. Final seeds were deliberately not consumed because M2 failed. We claim only: (i) low-value abstention can be made contract-equivalent, (ii) safe active allocation probing has a development-only nonempty region, and (iii) the registered cross-plant net-control-value claim is not supported and is terminated with decisive negative evidence.

## 7. Reproducibility statement

The review archive contains source, environment, tests, all development searches including failures, both M2 attempts, raw control-cycle trajectories, locked summaries, figures, and fresh-extract replay scripts. No failed episode was removed and `NOT_EVALUATED` was not counted as success or failure.
