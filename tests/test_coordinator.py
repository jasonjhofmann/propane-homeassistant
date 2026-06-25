"""Unit tests for Nee-Vo coordinator helpers and failure branches."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, PropertyMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pyneevo.errors import GenericHTTPError, InvalidCredentialsError

from custom_components.neevo.coordinator import (
    NeeVoCoordinator,
    _coerce_float,
    _safe_pressure,
    _sanitize_state,
    net_date_to_datetime,
)

from .conftest import make_entry, make_tank


def test_net_date_parsing() -> None:
    """The .NET /Date(ms)/ parser handles the suffix, None, and garbage."""
    parsed = net_date_to_datetime("/Date(1781028000000-0700)/")
    assert parsed == datetime(2026, 6, 9, 18, 0, tzinfo=UTC)
    # Epoch-ms is absolute UTC; the +0000 form lands on the same instant.
    assert net_date_to_datetime("/Date(1781028000000+0000)/") == parsed
    # A bare epoch with no tz suffix is still accepted.
    assert net_date_to_datetime("/Date(1781028000000)/") == parsed
    assert net_date_to_datetime(None) is None
    assert net_date_to_datetime("") is None
    assert net_date_to_datetime("not a date") is None


def test_net_date_rejects_malformed_digits() -> None:
    """A digit run not closed by a paren must reject, not parse a 1970 stub.

    The loose r"/Date\\((\\d+)" pattern would capture '123' from '/Date(123abc)/'
    and emit a nonsense 1970-era timestamp; the anchored pattern rejects it.
    """
    assert net_date_to_datetime("/Date(123abc456)/") is None
    assert net_date_to_datetime("/Date(abc)/") is None


def test_net_date_out_of_range_is_none() -> None:
    """An absurdly large epoch overflows fromtimestamp -> None, not a crash."""
    assert net_date_to_datetime("/Date(999999999999999999999)/") is None


def test_coerce_float() -> None:
    """_coerce_float accepts finite numbers and rejects junk/NaN/inf."""
    assert _coerce_float(3) == 3.0
    assert _coerce_float("4.5") == 4.5
    assert _coerce_float(None) is None
    assert _coerce_float("n/a") is None
    assert _coerce_float(float("nan")) is None
    assert _coerce_float(float("inf")) is None
    assert _coerce_float(float("-inf")) is None


def test_sanitize_state_rejects_non_mapping() -> None:
    """A non-dict blob from a corrupt Store yields empty state, not a crash."""
    assert _sanitize_state(["not", "a", "dict"]) == {}


def test_sanitize_state_drops_and_keeps() -> None:
    """Sanitize keeps valid fields, drops corrupt totals/rows, coerces ints."""
    t0 = datetime(2026, 6, 9, tzinfo=UTC).isoformat()
    stored = {
        "tank-ok": {
            "consumed_total_l": 12,  # int -> coerced to float
            "last_level_l": 500.0,
            "last_ts": t0,
            "history": [
                [t0, 620.0],
                ["bad-ts", 600.0],  # bad timestamp -> dropped
                [t0, "n/a"],  # bad liters -> dropped
                ["only-one-col"],  # wrong arity -> dropped
            ],
        },
        "tank-corrupt": {
            "consumed_total_l": "garbage",  # non-numeric -> dropped
            "last_level_l": -5.0,  # negative -> dropped
            "last_ts": 12345,  # non-string -> dropped
            "history": "not-a-list",
        },
        "tank-bad": "not-a-mapping",  # dropped entirely
    }
    clean = _sanitize_state(stored)

    assert set(clean) == {"tank-ok", "tank-corrupt"}
    ok = clean["tank-ok"]
    assert ok["consumed_total_l"] == 12.0
    assert ok["last_level_l"] == 500.0
    assert ok["last_ts"] == t0
    assert ok["history"] == [[t0, 620.0]]  # only the one valid row survives

    corrupt = clean["tank-corrupt"]
    assert "consumed_total_l" not in corrupt
    assert "last_level_l" not in corrupt
    assert "last_ts" not in corrupt
    assert "history" not in corrupt


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


def test_advance_rate_sub_minute_window_is_none() -> None:
    """Readings seconds apart fall under the elapsed floor -> None, no spike.

    Without the floor, a 120 L delta over a few seconds would divide out to an
    absurd multi-thousand gal/day rate.
    """
    from datetime import timedelta

    state: dict = {}
    t0 = datetime(2026, 6, 9, 12, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(seconds=5)
    assert NeeVoCoordinator._advance_rate(state, 620.0, t0) is None
    assert NeeVoCoordinator._advance_rate(state, 500.0, t1) is None


def test_build_tank_data_rejects_out_of_range_level() -> None:
    """A level outside 0-100 or a non-positive capacity yields no volume."""
    coordinator = NeeVoCoordinator.__new__(NeeVoCoordinator)
    coordinator._state = {}
    now = datetime(2026, 6, 9, tzinfo=UTC)

    over = NeeVoCoordinator._build_tank_data(
        coordinator, make_tank(level=150, capacity=1000.0), now
    )
    assert over.estimated_gal is None
    assert over.consumed_l is None

    negative_cap = NeeVoCoordinator._build_tank_data(
        coordinator, make_tank(level=50, capacity=-1000.0), now
    )
    assert negative_cap.estimated_gal is None
    assert negative_cap.capacity_l is None


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
