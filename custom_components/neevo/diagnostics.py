"""Diagnostics support for the Nee-Vo integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import NeeVoConfigEntry

# Keys redacted at any depth: credentials, tank identity, and any
# address/geolocation fields that can appear in a tank's raw .data. Both the
# NeeVoTankData dataclass field names (tank_id, serial) and the raw Otodata
# casings (Id, SerialNumber, ...) are listed so nesting is scrubbed either way.
TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "serial",
    "SerialNumber",
    "tank_id",
    "id",
    "Id",
    "Address",
    "Latitude",
    "Longitude",
    "CustomName",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NeeVoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the config entry and its tanks."""
    coordinator = entry.runtime_data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "last_update_success": coordinator.last_update_success,
        "last_exception": (
            str(coordinator.last_exception) if coordinator.last_exception else None
        ),
        "tanks": [
            async_redact_data(asdict(tank), TO_REDACT)
            for tank in coordinator.data.values()
        ],
    }
