"""Unit tests for Nee-Vo coordinator helpers and failure branches."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, PropertyMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pyneevo.errors import GenericHTTPError, InvalidCredentialsError

from custom_components.neevo.coordinator import (
    NeeVoCoordinator,
    _safe_pressure,
    net_date_to_datetime,
)

from .conftest import make_entry, make_tank


def test_net_date_parsing() -> None:
    """The .NET /Date(ms)/ parser handles the suffix, None, and garbage."""
    parsed = net_date_to_datetime("/Date(1781028000000-0700)/")
    assert parsed == datetime(2026, 6, 9, 18, 0, tzinfo=UTC)
    # Epoch-ms is absolute UTC; the +0000 form lands on the same instant.
    assert net_date_to_datetime("/Date(1781028000000+0000)/") == parsed
    assert net_date_to_datetime(None) is None
    assert net_date_to_datetime("") is None
    assert net_date_to_datetime("not a date") is None


def test_advance_consumed_seed_then_drop_then_refill() -> None:
    """Forward-only meter: seed emits None, drops add, refills are ignored."""
    state: dict = {}
    t0 = datetime(2026, 6, 9, tzinfo=UTC)
    t1 = datetime(2026, 6, 10, tzinfo=UTC)
    t2 = datetime(2026, 6, 11, tzinfo=UTC)
    t3 = datetime(2026, 6, 12, tzinfo=UTC)

    assert NeeVoCoordinator._advance_consumed(state, 620.0, t0) is None
    assert NeeVoCoordinator._advance_consumed(state, 500.0, t1) == 120.0
    # Refill upward: total holds.
    assert NeeVoCoordinator._advance_consumed(state, 800.0, t2) == 120.0
    # A missing current reading returns the persisted total unchanged.
    assert NeeVoCoordinator._advance_consumed(state, None, t3) == 120.0


def test_advance_rate_needs_two_readings() -> None:
    """Rate is None on the first reading, then a downward-step gal/day rate."""
    state: dict = {}
    t0 = datetime(2026, 6, 9, tzinfo=UTC)
    t1 = datetime(2026, 6, 10, tzinfo=UTC)

    assert NeeVoCoordinator._advance_rate(state, 620.0, t0) is None
    # 120 L drop over 1 day = 120 / 3.785411784 = 31.701 gal/day.
    assert NeeVoCoordinator._advance_rate(state, 500.0, t1) == 31.701
    # A None reading yields no rate for this cycle.
    assert NeeVoCoordinator._advance_rate(state, None, t1) is None


def test_advance_rate_same_instant_is_none() -> None:
    """Two readings at the same instant give zero elapsed time -> None."""
    state: dict = {}
    t0 = datetime(2026, 6, 9, tzinfo=UTC)
    assert NeeVoCoordinator._advance_rate(state, 620.0, t0) is None
    assert NeeVoCoordinator._advance_rate(state, 500.0, t0) is None


async def test_relogin_transport_error_is_update_failed(
    hass: HomeAssistant, mock_api
) -> None:
    """An auth failure whose recovery login hits a transport error -> UpdateFailed."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    mock_api.refresh_tanks.side_effect = InvalidCredentialsError("expired")
    mock_api.login.side_effect = GenericHTTPError("503")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_transport_error_is_update_failed(hass: HomeAssistant, mock_api) -> None:
    """A plain transport error on refresh (no auth involved) -> UpdateFailed."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    mock_api.refresh_tanks.side_effect = GenericHTTPError("503")
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def test_advance_rate_skips_malformed_ring_rows() -> None:
    """A corrupt timestamp in the persisted ring is dropped, not crashed on."""
    t0 = datetime(2026, 6, 9, tzinfo=UTC)
    state = {"history": [["not-a-timestamp", 700.0]]}
    # Only the freshly appended valid row remains parseable -> <2 rows -> None.
    assert NeeVoCoordinator._advance_rate(state, 620.0, t0) is None


def test_safe_pressure_missing_field_returns_none() -> None:
    """A real pyneevo Tank does a bare dict[...] for pressure, so a payload that
    omits the field raises KeyError; it must be swallowed, not fail the poll."""
    tank = MagicMock()
    type(tank).tank_last_pressure = PropertyMock(
        side_effect=KeyError("TankLastPressure")
    )
    assert _safe_pressure(tank) == (None, None)


def test_safe_pressure_non_numeric_keeps_unit() -> None:
    """A non-numeric pressure coerces to None but keeps the reported unit."""
    tank = MagicMock()
    tank.tank_last_pressure = "n/a"
    tank.tank_last_pressure_unit = "psi"
    assert _safe_pressure(tank) == (None, "psi")


def test_safe_pressure_none_value() -> None:
    """A null pressure yields None without raising."""
    tank = MagicMock()
    tank.tank_last_pressure = None
    tank.tank_last_pressure_unit = None
    assert _safe_pressure(tank) == (None, None)


def test_safe_pressure_valid() -> None:
    """A numeric pressure is returned with its unit."""
    tank = MagicMock()
    tank.tank_last_pressure = 30.5
    tank.tank_last_pressure_unit = "psi"
    assert _safe_pressure(tank) == (30.5, "psi")


async def test_store_state_survives_reload(hass: HomeAssistant, mock_api) -> None:
    """The persisted consumed total is reloaded into a fresh coordinator."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    # Drive one drop so a non-zero consumed total is persisted, then flush.
    mock_api.get_tanks_info.return_value = {make_tank(level=50).id: make_tank(level=50)}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    await coordinator._async_save()

    # Reload: a new coordinator loads the saved state from the Store.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = entry.runtime_data
    assert reloaded._state  # non-empty: the prior series was restored

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
