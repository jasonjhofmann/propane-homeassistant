"""Sensors for the Nee-Vo integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPressure, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import NeeVoConfigEntry, NeeVoCoordinator, NeeVoTankData
from .entity import NeeVoEntity

PARALLEL_UPDATES = 0

# Custom unit for the gal/day rate. VOLUME_FLOW_RATE is intentionally NOT used:
# its device class rejects a per-day gallon unit (unit-validation failure).
UNIT_GALLONS_PER_DAY = "gal/d"

# Otodata pressure-unit strings mapped to HA pressure units. Unknown strings
# leave the pressure sensor without a unit (and no device class).
_PRESSURE_UNITS: dict[str, str] = {
    "psi": UnitOfPressure.PSI,
    "psig": UnitOfPressure.PSI,
    "kpa": UnitOfPressure.KPA,
    "bar": UnitOfPressure.BAR,
    "mbar": UnitOfPressure.MBAR,
    "hpa": UnitOfPressure.HPA,
}


@dataclass(frozen=True, kw_only=True)
class NeeVoSensorEntityDescription(SensorEntityDescription):
    """Describes a Nee-Vo sensor and how to read its value from tank data."""

    # The timestamp sensor returns a datetime, which is outside StateType.
    value_fn: Callable[[NeeVoTankData], StateType | datetime]
    exists_fn: Callable[[NeeVoTankData], bool] = lambda _: True


SENSOR_DESCRIPTIONS: tuple[NeeVoSensorEntityDescription, ...] = (
    NeeVoSensorEntityDescription(
        key="level",
        translation_key="level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=lambda tank: tank.level_pct,
    ),
    NeeVoSensorEntityDescription(
        key="estimated_volume",
        translation_key="estimated_volume",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.GALLONS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda tank: tank.estimated_gal,
    ),
    NeeVoSensorEntityDescription(
        key="last_reading",
        translation_key="last_reading",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda tank: tank.last_reading,
    ),
    NeeVoSensorEntityDescription(
        key="consumption_rate",
        translation_key="consumption_rate",
        native_unit_of_measurement=UNIT_GALLONS_PER_DAY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gas-burner",
        value_fn=lambda tank: tank.rate_gal_per_day,
    ),
    NeeVoSensorEntityDescription(
        key="consumed",
        translation_key="consumed",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:propane-tank",
        value_fn=lambda tank: tank.consumed_l,
    ),
    NeeVoSensorEntityDescription(
        key="pressure",
        translation_key="pressure",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda tank: tank.pressure,
        exists_fn=lambda tank: tank.pressure is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: NeeVoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Nee-Vo sensors for every tank on the account."""
    coordinator = config_entry.runtime_data
    async_add_entities(
        NeeVoSensor(coordinator, tank_id, description)
        for tank_id, tank in coordinator.data.items()
        for description in SENSOR_DESCRIPTIONS
        if description.exists_fn(tank)
    )


class NeeVoSensor(NeeVoEntity, SensorEntity):
    """A single Nee-Vo tank sensor."""

    entity_description: NeeVoSensorEntityDescription

    def __init__(
        self,
        coordinator: NeeVoCoordinator,
        tank_id: str,
        description: NeeVoSensorEntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator, tank_id)
        self.entity_description = description
        self._attr_unique_id = f"{tank_id}_{description.key}"
        if description.key == "pressure":
            self._attr_native_unit_of_measurement = _PRESSURE_UNITS.get(
                (self.tank.pressure_unit or "").strip().lower()
            )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value from the current tank snapshot."""
        return self.entity_description.value_fn(self.tank)
