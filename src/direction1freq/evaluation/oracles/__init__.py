"""Evaluation-only Oracles that may receive simulator truth."""

from .current_capability_nmpc import CurrentCapabilityNMPCOracle, OracleNMPCDiagnostics

__all__ = ["CurrentCapabilityNMPCOracle", "OracleNMPCDiagnostics"]
