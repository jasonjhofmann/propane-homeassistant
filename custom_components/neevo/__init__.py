"""The Nee-Vo integration."""

from __future__ import annotations

import asyncio
import logging

from aiohttp.client_exceptions import ClientError
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from pyneevo import NeeVoApiInterface
from pyneevo.errors import GenericHTTPError, InvalidCredentialsError, PyNeeVoError

from .const import DOMAIN, REQUEST_TIMEOUT
from .coordinator import NeeVoConfigEntry, NeeVoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: NeeVoConfigEntry) -> bool:
    """Set up Nee-Vo from a config entry."""
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            api = await NeeVoApiInterface.login(
                entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
            )
    except InvalidCredentialsError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="invalid_auth",
        ) from err
    except (GenericHTTPError, ClientError, PyNeeVoError, TimeoutError) as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err) or type(err).__name__},
        ) from err

    coordinator = NeeVoCoordinator(hass, entry, api)
    # Load the persisted consumed-meter / rate-ring state BEFORE the first
    # refresh so the first observation extends the saved series rather than
    # re-seeding it (which would drop the running consumed total).
    await coordinator.async_load_store()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NeeVoConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
