"""Config flow for the Nee-Vo integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp.client_exceptions import ClientError
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from pyneevo import NeeVoApiInterface
from pyneevo.errors import GenericHTTPError, InvalidCredentialsError, PyNeeVoError

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


async def _async_validate(email: str, password: str) -> dict[str, str]:
    """Validate credentials and the presence of at least one tank.

    Returns a ``{"base": error}`` mapping; empty on success.
    """
    try:
        api = await NeeVoApiInterface.login(email, password)
        tanks = await api.get_tanks_info()
    except InvalidCredentialsError:
        return {"base": "invalid_auth"}
    except (GenericHTTPError, ClientError, PyNeeVoError, TimeoutError):
        return {"base": "cannot_connect"}
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating Nee-Vo credentials")
        return {"base": "unknown"}
    if not tanks:
        return {"base": "no_tanks"}
    return {}


class NeeVoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Nee-Vo config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: email + password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            errors = await _async_validate(email, password)
            if not errors:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication on rejected credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password (email is fixed) and re-validate."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        email = entry.data[CONF_EMAIL]
        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            errors = await _async_validate(email, password)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: password},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={CONF_EMAIL: email},
            errors=errors,
        )
