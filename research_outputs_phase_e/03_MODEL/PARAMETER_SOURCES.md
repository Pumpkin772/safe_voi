# Parameter sources and scope

Plant A values are transparent study parameters inherited from the corrected Direction1 aggregate model and are sensitivity-tested over 2/4 s control and 0.01--0.1 s integration.  The 5% droop and `B=D+1/R` ACE bias are explicit; no hidden OEM values are claimed.  BESS rating, energy, efficiency, ramp, and delay are declared engineering assumptions and will be varied in known/OOD factors.

Plant B values are read from the bundled ANDES 2.0.0 Kundur VSC case at runtime.  Its 60 Hz/100 MVA base is not silently overwritten.  The external 1000 MVA study interface applies an explicit factor-ten power conversion.  Native-network validation is empirical RMS/DAE evidence, not an EMT or hardware claim.
