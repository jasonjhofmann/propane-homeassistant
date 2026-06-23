"""Fixtures for the Nee-Vo tests.

Everything here is SYNTHETIC — no real account, email, serial, or tank ID.
The pyneevo API is fully mocked so the tests never touch the network.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.neevo.const import DOMAIN

# Synthetic credentials and tank metadata.
TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "hunter2"
TANK_ID = "100000000001"
TANK_SERIAL = "TM00000001"
TANK_NAME = "Test Tank"
TANK_LEVEL = 62
TANK_CAPACITY_L = 1000.0
# .NET /Date(ms)/ for 2026-06-09T18:00:00Z (epoch-ms is absolute UTC).
LAST_READING_NET = "/Date(1781028000000-0700)/"


def make_tank(
    level: int | None = TANK_LEVEL,
    capacity: float | None = TANK_CAPACITY_L,
    pressure: float | None = None,
    pressure_unit: str | None = None,
):
    """Build a fake pyneevo Tank with synthetic data."""
    tank = MagicMock()
    tank.id = TANK_ID
    tank.name = TANK_NAME
    tank.serial_number = TANK_SERIAL
    tank.level = level
    tank.tank_capacity = capacity
    tank.product = "Propane"
    tank.tank_last_pressure = pressure
    tank.tank_last_pressure_unit = pressure_unit
    tank.data = {
        "Id": TANK_ID,
        "CustomName": TANK_NAME,
        "SerialNumber": TANK_SERIAL,
        "Level": level,
        "TankCapacity": capacity,
        "LastReadingDate": LAST_READING_NET,
        "Address": "123 Synthetic St",
        "Latitude": 36.0,
        "Longitude": -115.0,
    }
    return tank


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield


@pytest.fixture
def mock_tank():
    """Provide a default synthetic tank."""
    return make_tank()


@pytest.fixture
def mock_api(mock_tank):
    """Mock NeeVoApiInterface everywhere it is constructed.

    ``login`` is patched in both __init__ and config_flow; the returned API has
    async ``get_tanks_info`` / ``refresh_tanks``.
    """
    api = MagicMock()
    api.get_tanks_info = AsyncMock(return_value={TANK_ID: mock_tank})
    api.refresh_tanks = AsyncMock(return_value=None)

    login = AsyncMock(return_value=api)
    with (
        patch(
            "custom_components.neevo.NeeVoApiInterface.login",
            login,
        ),
        patch(
            "custom_components.neevo.config_flow.NeeVoApiInterface.login",
            login,
        ),
        patch(
            "custom_components.neevo.coordinator.NeeVoApiInterface.login",
            login,
        ),
    ):
        api.login = login
        yield api


def make_entry(
    email: str = TEST_EMAIL, password: str = TEST_PASSWORD
) -> MockConfigEntry:
    """Build a Nee-Vo MockConfigEntry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=email,
        data={CONF_EMAIL: email, CONF_PASSWORD: password},
        unique_id=email.lower(),
    )
