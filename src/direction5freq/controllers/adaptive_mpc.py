"""Rolling public-I/O adaptive MPC baseline."""

from __future__ import annotations

from .dcsv_mpc_final import DisturbanceCapabilitySeparatedViabilityMPC


class ModelAdaptiveMPC(DisturbanceCapabilitySeparatedViabilityMPC):
    """A true rolling comparator using the online envelope without recourse."""

    name = "model_adaptive_mpc"
    is_true_rolling_mpc = True

    def __init__(self, *args, **kwargs) -> None:
        kwargs["use_online_performance"] = True
        kwargs["name"] = self.name
        super().__init__(*args, **kwargs)


__all__ = ["ModelAdaptiveMPC"]

