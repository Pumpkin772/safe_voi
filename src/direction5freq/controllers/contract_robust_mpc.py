"""Fair contract and nominal rolling-MPC baselines."""

from __future__ import annotations

from direction5freq.models.capability_contract import CapabilityContract
from direction5freq.models.plant_a_full import PlantAParameters

from .dcsv_mpc_final import RollingContractMPC


class ContractOnlyRollingRobustMPC(RollingContractMPC):
    name = "contract_only_rolling_mpc"


class NominalOffsetFreeMPC(RollingContractMPC):
    name = "nominal_offset_free_mpc"

    def __init__(
        self,
        period_s: float,
        horizon_steps: int = 8,
        plant_parameters: PlantAParameters | None = None,
    ) -> None:
        super().__init__(period_s, horizon_steps, plant_parameters)
        self.contract = CapabilityContract(
            lower_power_pu=(-0.080, -0.080),
            upper_power_pu=(0.080, 0.080),
            ramp_down_pu_per_s=(0.060, 0.060),
            ramp_up_pu_per_s=(0.060, 0.060),
            maximum_delay_s=(0.20, 0.20),
        )


__all__ = ["ContractOnlyRollingRobustMPC", "NominalOffsetFreeMPC"]

