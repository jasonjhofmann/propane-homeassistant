"""Tests for the Nee-Vo base entity (device info + availability)."""

from homeassistant.core import HomeAssistant
from pyneevo.errors import GenericHTTPError

from .conftest import TANK_ID, make_entry, make_tank


async def test_available_reflects_tank_presence(hass: HomeAssistant, mock_api) -> None:
    """The entity goes unavailable when its tank drops out of the feed.

    Covers the per-tank availability override in NeeVoEntity.available, which
    AND-s the coordinator's own availability with the tank still being present
    in coordinator.data.
    """
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    level = hass.states.get("sensor.test_tank_tank_level")
    assert level is not None and level.state == "62"

    # A successful refresh that no longer lists this tank: the coordinator stays
    # healthy, but the entity must report unavailable via the override.
    mock_api.get_tanks_info.return_value = {"other-tank": make_tank()}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success
    assert TANK_ID not in coordinator.data
    assert hass.states.get("sensor.test_tank_tank_level").state == "unavailable"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_unavailable_on_coordinator_failure(
    hass: HomeAssistant, mock_api
) -> None:
    """A failed update marks the entity unavailable through the base class."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    mock_api.refresh_tanks.side_effect = GenericHTTPError("503")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("sensor.test_tank_tank_level").state == "unavailable"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
