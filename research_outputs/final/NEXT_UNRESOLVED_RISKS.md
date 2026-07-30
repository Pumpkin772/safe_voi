# Three most severe unresolved limitations

1. Plant B experiments use an independent four-machine/six-bus RMS/network DAE that is cross-qualified against native ANDES Kundur PFlow/TDS; the controller is not injected directly into the native ANDES dynamic model, and no EMT/OEM fidelity is claimed.
2. The selected C6-A continuous responsibility rule is dominated by robust capability-set MPC in final continuous metrics, especially OOD; its conditional theory does not supply empirical superiority.
3. C5 identification uses controlled single-mechanism passive traces, while final compound/drift/multiple-switch OOD cases are not re-qualified for source macro-F1 and `Tdet<Tcrit`; O2 also fails many final performance episodes despite successful solves and is not a general optimal ceiling.
