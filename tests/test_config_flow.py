"""Tests for the Nee-Vo config and reauth flows."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pyneevo.errors import GenericHTTPError, InvalidCredentialsError

from custom_components.neevo.const import DOMAIN

from .conftest import TEST_EMAIL, TEST_PASSWORD, make_entry

USER_INPUT = {CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD}


async def test_user_flow_success(hass: HomeAssistant, mock_api) -> None:
    """Happy path: validate credentials and create the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == TEST_EMAIL
    assert result["data"] == {CONF_EMAIL: TEST_EMAIL, CONF_PASSWORD: TEST_PASSWORD}
    assert result["result"].unique_id == TEST_EMAIL.lower()


async def test_user_flow_invalid_auth(hass: HomeAssistant, mock_api) -> None:
    """A rejected login surfaces invalid_auth, then the flow recovers."""
    mock_api.login.side_effect = InvalidCredentialsError("bad creds")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    mock_api.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_cannot_connect(hass: HomeAssistant, mock_api) -> None:
    """A transport error surfaces cannot_connect."""
    mock_api.login.side_effect = GenericHTTPError("503")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass: HomeAssistant, mock_api) -> None:
    """An unexpected error surfaces the unknown error."""
    mock_api.login.side_effect = RuntimeError("surprise")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_user_flow_no_tanks(hass: HomeAssistant, mock_api) -> None:
    """An account with no tanks surfaces no_tanks."""
    mock_api.get_tanks_info.return_value = {}

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_tanks"}


async def test_user_flow_already_configured(hass: HomeAssistant, mock_api) -> None:
    """A second entry for the same account aborts."""
    make_entry().add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_success(hass: HomeAssistant, mock_api) -> None:
    """Reauth rejects a bad password, then accepts a good one."""
    entry = make_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    mock_api.login.side_effect = InvalidCredentialsError("bad creds")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "wrong"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    mock_api.login.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new-password"
    assert entry.data[CONF_EMAIL] == TEST_EMAIL

    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reauth_cannot_connect(hass: HomeAssistant, mock_api) -> None:
    """A transport error during reauth keeps the form open."""
    entry = make_entry()
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    mock_api.login.side_effect = GenericHTTPError("503")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
