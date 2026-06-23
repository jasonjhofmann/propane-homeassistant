"""Base entity for the Nee-Vo integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, MANUFACTURER, MODEL
from .coordinator import NeeVoCoordinator, NeeVoTankData


class NeeVoEntity(CoordinatorEntity[NeeVoCoordinator]):
    """Base entity tied to a single tank device."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: NeeVoCoordinator, tank_id: str) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._tank_id = tank_id
        tank = coordinator.data[tank_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tank_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=tank.name,
            # pyneevo can hand back the serial as an int; the device registry
            # requires a string (HA frame warning, hard error from 2026.12.0).
            serial_number=str(tank.serial) if tank.serial is not None else None,
        )

    @property
    def tank(self) -> NeeVoTankData:
        """Return this entity's current tank snapshot."""
        return self.coordinator.data[self._tank_id]

    @property
    def available(self) -> bool:
        """Stay unavailable while the tank drops out of the feed."""
        return super().available and self._tank_id in self.coordinator.data
