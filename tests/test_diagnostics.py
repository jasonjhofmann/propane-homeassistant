"""Tests for Nee-Vo diagnostics redaction."""

from homeassistant.core import HomeAssistant

from custom_components.neevo.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import TANK_ID, TANK_SERIAL, TEST_EMAIL, make_entry


async def test_diagnostics_redacts_secrets(hass: HomeAssistant, mock_api) -> None:
    """Email, password, serial, tank id, and address fields are redacted."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry_data"]["email"] == "**REDACTED**"
    assert diag["entry_data"]["password"] == "**REDACTED**"
    assert diag["last_update_success"] is True
    assert len(diag["tanks"]) == 1

    tank = diag["tanks"][0]
    # Dataclass-level identity fields are redacted.
    assert tank["serial"] == "**REDACTED**"
    assert tank["tank_id"] == "**REDACTED**"
    # The raw .data nested dict is scrubbed too.
    raw = tank["raw"]
    assert raw["SerialNumber"] == "**REDACTED**"
    assert raw["Id"] == "**REDACTED**"
    assert raw["Address"] == "**REDACTED**"
    assert raw["Latitude"] == "**REDACTED**"
    assert raw["Longitude"] == "**REDACTED**"

    # The serialized dump never leaks the real values anywhere.
    blob = str(diag)
    assert TEST_EMAIL not in blob
    assert TANK_SERIAL not in blob
    assert TANK_ID not in blob

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
