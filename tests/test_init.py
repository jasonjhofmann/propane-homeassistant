"""Tests for Nee-Vo setup, unload, and coordinator failure modes."""

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from pyneevo.errors import GenericHTTPError, InvalidCredentialsError

from .conftest import make_entry


async def test_setup_and_unload(hass: HomeAssistant, mock_api) -> None:
    """Entry sets up with a tank and unloads cleanly."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_auth_failure_starts_reauth(hass: HomeAssistant, mock_api) -> None:
    """Bad credentials at setup fail the entry and start reauth."""
    mock_api.login.side_effect = InvalidCredentialsError("bad creds")
    entry = make_entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))


async def test_setup_connection_error_is_not_ready(
    hass: HomeAssistant, mock_api
) -> None:
    """A transport error at setup yields SETUP_RETRY (ConfigEntryNotReady)."""
    mock_api.login.side_effect = GenericHTTPError("503")
    entry = make_entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_first_refresh_error_is_not_ready(
    hass: HomeAssistant, mock_api
) -> None:
    """Login succeeds but the first refresh's fetch fails -> SETUP_RETRY.

    Exercises the first_refresh path (not the login try/except), which raises
    ConfigEntryNotReady from the coordinator rather than __init__.
    """
    mock_api.refresh_tanks.side_effect = GenericHTTPError("503")
    entry = make_entry()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_refresh_auth_failure_triggers_reauth(
    hass: HomeAssistant, mock_api
) -> None:
    """A mid-refresh auth failure that re-login can't fix starts reauth."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    coordinator = entry.runtime_data
    # Both the in-place refresh and the recovery re-login reject the creds.
    mock_api.refresh_tanks.side_effect = InvalidCredentialsError("expired")
    mock_api.login.side_effect = InvalidCredentialsError("expired")
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not coordinator.last_update_success
    assert any(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_refresh_empty_tanks_is_update_failed(
    hass: HomeAssistant, mock_api
) -> None:
    """An empty tank map (the pyneevo finally-block quirk) -> UpdateFailed."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    mock_api.get_tanks_info.return_value = {}
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert not coordinator.last_update_success

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_refresh_relogin_recovers(hass: HomeAssistant, mock_api) -> None:
    """An expired session that re-login fixes keeps the coordinator healthy."""
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    # First refresh_tanks raises auth; the recovery login + get_tanks_info work.
    mock_api.refresh_tanks.side_effect = InvalidCredentialsError("expired")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.last_update_success

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
