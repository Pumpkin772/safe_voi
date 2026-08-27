"""Physical service-resource value coordinates for the positive-region map."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutcomeValueComponents:
    """Comparator cost minus method cost in three physical coordinates."""

    grid_service_s: float
    sg_mechanical_mileage_pu: float
    bess_energy_throughput_pu_s: float

    def priced_value(
        self,
        *,
        sg_mileage_price_s_per_pu: float,
        bess_throughput_price: float,
    ) -> float:
        return (
            self.grid_service_s
            + sg_mileage_price_s_per_pu * self.sg_mechanical_mileage_pu
            + bess_throughput_price * self.bess_energy_throughput_pu_s
        )

    def mix(self, other: "OutcomeValueComponents", other_probability: float) -> "OutcomeValueComponents":
        probability = float(other_probability)
        return OutcomeValueComponents(
            grid_service_s=(1.0 - probability) * self.grid_service_s
            + probability * other.grid_service_s,
            sg_mechanical_mileage_pu=(
                (1.0 - probability) * self.sg_mechanical_mileage_pu
                + probability * other.sg_mechanical_mileage_pu
            ),
            bess_energy_throughput_pu_s=(
                (1.0 - probability) * self.bess_energy_throughput_pu_s
                + probability * other.bess_energy_throughput_pu_s
            ),
        )

    def break_even_bess_throughput_price(
        self,
        *,
        sg_mileage_price_s_per_pu: float,
    ) -> float | None:
        """Largest BESS price with positive value when throughput increases."""

        intercept = (
            self.grid_service_s
            + sg_mileage_price_s_per_pu * self.sg_mechanical_mileage_pu
        )
        slope = self.bess_energy_throughput_pu_s
        if slope >= 0.0:
            return None
        return max(0.0, intercept / -slope)
