"""Tests for Nee-Vo sensors and the derived consumed/rate series."""

from datetime import UTC, datetime
from unittest.mock import patch

from homeassistant.const import UnitOfPressure, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.neevo.const import DOMAIN

from .conftest import TANK_CAPACITY_L, TANK_ID, make_entry, make_tank


def state_by_unique_id(hass: HomeAssistant, unique_id: str):
    """Look up a sensor state via its registry unique_id."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id, f"no entity registered for {unique_id}"
    return hass.states.get(entity_id)


async def test_sensors_created_with_values(hass: HomeAssistant, mock_api) -> None:
    """The core sensors are created with the expected values."""
    # Use US customary units so the native gallons/psi the integration emits
    # are shown as-authored rather than auto-converted to metric for display.
    hass.config.units = US_CUSTOMARY_SYSTEM
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # level 62% of 1000 L = 620 L -> 620 / 3.785411784 = 163.8 gal.
    assert state_by_unique_id(hass, f"{TANK_ID}_level").state == "62"
    assert state_by_unique_id(hass, f"{TANK_ID}_estimated_volume").state == "163.8"

    volume = state_by_unique_id(hass, f"{TANK_ID}_estimated_volume")
    assert volume.attributes["unit_of_measurement"] == UnitOfVolume.GALLONS

    # Last reading parsed from the synthetic .NET date (2026-06-09T18:00:00Z).
    last = state_by_unique_id(hass, f"{TANK_ID}_last_reading")
    assert last.state == "2026-06-09T18:00:00+00:00"

    # Consumed publishes nothing on the first observation (baseline seed).
    assert state_by_unique_id(hass, f"{TANK_ID}_consumed").state == "unknown"
    # Rate needs >=2 readings.
    assert state_by_unique_id(hass, f"{TANK_ID}_consumption_rate").state == "unknown"

    # No pressure sensor when the tank reports none.
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{TANK_ID}_pressure") is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_pressure_sensor_when_reported(hass: HomeAssistant, mock_api) -> None:
    """A pressure-reporting tank gets a diagnostic pressure sensor with a unit."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    mock_api.get_tanks_info.return_value = {
        TANK_ID: make_tank(pressure=42.0, pressure_unit="psi")
    }
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    pressure = state_by_unique_id(hass, f"{TANK_ID}_pressure")
    assert pressure.state == "42.0"
    assert pressure.attributes["unit_of_measurement"] == UnitOfPressure.PSI

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_consumed_and_rate_accumulate(hass: HomeAssistant, mock_api) -> None:
    """Consumed accumulates on drops, ignores refills; rate warms up.

    Three observations a day apart: seed at 62% -> drop to 50% (120 L consumed)
    -> refill to 80% (ignored, total unchanged). The rate is computed from the
    downward steps over the ring's span.
    """
    day0 = datetime(2026, 6, 9, 12, 0, tzinfo=UTC)
    day1 = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    day2 = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)

    entry = make_entry()
    entry.add_to_hass(hass)

    with patch("custom_components.neevo.coordinator.datetime") as mock_dt:
        mock_dt.now.return_value = day0
        mock_dt.fromtimestamp.side_effect = datetime.fromtimestamp
        mock_dt.fromisoformat.side_effect = datetime.fromisoformat
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data

        # First poll seeds the baseline only.
        assert state_by_unique_id(hass, f"{TANK_ID}_consumed").state == "unknown"

        # Second poll: 62% -> 50% is a 12% drop of 1000 L = 120 L consumed.
        mock_api.get_tanks_info.return_value = {TANK_ID: make_tank(level=50)}
        mock_dt.now.return_value = day1
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state_by_unique_id(hass, f"{TANK_ID}_consumed").state == "120.0"
        # Two readings (620 L, 500 L) over 1 day: 120 L / 3.785... = 31.701 gal/d.
        assert state_by_unique_id(hass, f"{TANK_ID}_consumption_rate").state == "31.701"

        # Third poll: a refill to 80% must NOT decrease the consumed total.
        mock_api.get_tanks_info.return_value = {TANK_ID: make_tank(level=80)}
        mock_dt.now.return_value = day2
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state_by_unique_id(hass, f"{TANK_ID}_consumed").state == "120.0"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_estimated_volume_none_without_capacity(
    hass: HomeAssistant, mock_api
) -> None:
    """Missing capacity leaves the volume/consumed series unpopulated."""
    mock_api.get_tanks_info.return_value = {TANK_ID: make_tank(level=62, capacity=None)}
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert state_by_unique_id(hass, f"{TANK_ID}_level").state == "62"
    assert state_by_unique_id(hass, f"{TANK_ID}_estimated_volume").state == "unknown"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_device_serial_coerced_to_string(hass: HomeAssistant, mock_api) -> None:
    """An int serial from pyneevo is stored as a string on the device.

    The device registry rejects a non-string serial_number (HA frame warning,
    hard error from 2026.12.0), but pyneevo hands the serial back as an int.
    """
    mock_api.get_tanks_info.return_value = {TANK_ID: make_tank(serial=12345678)}
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, TANK_ID)})
    assert device is not None
    assert device.serial_number == "12345678"
    assert isinstance(device.serial_number, str)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def test_capacity_sanity() -> None:
    """Document the synthetic capacity used by the value assertions above."""
    assert TANK_CAPACITY_L == 1000.0
