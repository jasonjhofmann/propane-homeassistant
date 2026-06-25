"""DataUpdateCoordinator for the Nee-Vo integration.

Holds a logged-in :class:`pyneevo.NeeVoApiInterface` and turns each tank's
cloud telemetry into a :class:`NeeVoTankData` snapshot. Two derived series are
maintained across polls and persisted to a :class:`homeassistant.helpers.storage.Store`:

* a **forward-only consumed-liters meter** (``consumed_l``) — the sum of
  downward level steps observed since setup, never decreasing, for the Energy
  dashboard's gas-consumption slot; and
* a **gal/day consumption rate** (``rate_gal_per_day``) derived from a trailing
  ring of ``(timestamp, liters)`` observations.

Because pyneevo exposes only the *current* reading (no historical level series),
both series warm up over successive polls rather than being backfilled.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp.client_exceptions import ClientError
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from pyneevo import NeeVoApiInterface, Tank
from pyneevo.errors import GenericHTTPError, InvalidCredentialsError, PyNeeVoError

from .const import (
    DOMAIN,
    LITERS_PER_GALLON,
    MAX_RATE_HISTORY_DAYS,
    MIN_RATE_ELAPSED_DAYS,
    REQUEST_TIMEOUT,
    STORAGE_VERSION,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

type NeeVoConfigEntry = ConfigEntry[NeeVoCoordinator]

# Debounce the Store writes so a burst of refreshes coalesces into one save.
_SAVE_DELAY = 30.0

# Anchor the full epoch-ms token: digits must be followed by the optional
# ``±hhmm`` tz suffix and a closing paren. A loose ``\d+`` would happily match
# the leading digits of a corrupt payload like ``/Date(123abc)/`` and yield a
# nonsense 1970-era timestamp instead of rejecting it.
_NET_DATE_RE = re.compile(r"/Date\((-?\d+)(?:[-+]\d+)?\)")


def net_date_to_datetime(value: str | None) -> datetime | None:
    """Parse a .NET ``/Date(ms±tz)/`` string to a UTC datetime (or ``None``).

    The leading epoch-milliseconds is absolute UTC; the optional ``±tz`` suffix
    is only display information and is ignored. Ported from the upstream
    pyscript ``_net_date_iso`` helper. A missing, malformed, or out-of-range
    payload yields ``None`` rather than a bogus date or an uncaught exception
    that would fail the whole poll.
    """
    if not value:
        return None
    match = _NET_DATE_RE.search(value)
    if not match:
        _LOGGER.debug("Unparseable Nee-Vo reading date: %r", value)
        return None
    try:
        return datetime.fromtimestamp(int(match.group(1)) / 1000, UTC)
    except (OverflowError, ValueError, OSError):
        _LOGGER.debug("Out-of-range Nee-Vo reading date: %r", value)
        return None


@dataclass
class NeeVoTankData:
    """A single tank's derived telemetry for one coordinator cycle."""

    tank_id: str
    name: str
    serial: str | None
    level_pct: int | None
    capacity_l: float | None
    estimated_gal: float | None
    last_reading: datetime | None
    consumed_l: float | None
    rate_gal_per_day: float | None
    pressure: float | None
    pressure_unit: str | None
    raw: dict[str, Any]


class NeeVoCoordinator(DataUpdateCoordinator[dict[str, NeeVoTankData]]):
    """Poll the Nee-Vo cloud for every tank on the account."""

    config_entry: NeeVoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: NeeVoConfigEntry,
        api: NeeVoApiInterface,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self._email = config_entry.data[CONF_EMAIL]
        self._password = config_entry.data[CONF_PASSWORD]
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{config_entry.entry_id}"
        )
        # Per tank id: {consumed_total_l, last_level_l, last_ts, history}.
        self._state: dict[str, dict[str, Any]] = {}
        self._save_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=_SAVE_DELAY,
            immediate=False,
            function=self._async_save,
        )

    async def async_load_store(self) -> None:
        """Load the persisted per-tank meter/ring state before first refresh.

        The Store is on-disk JSON that survives upgrades and can be hand-edited
        or truncated, so every value is validated before it is trusted: a
        corrupt total or a malformed ring row must not crash a later poll. See
        :func:`_sanitize_state`.
        """
        stored = await self._store.async_load()
        if stored:
            self._state = _sanitize_state(stored)
            _LOGGER.debug(
                "Loaded persisted Nee-Vo state for %d tank(s)", len(self._state)
            )
        else:
            _LOGGER.debug("No persisted Nee-Vo state found; starting fresh")

    async def _async_save(self) -> None:
        """Persist the per-tank meter/ring state."""
        _LOGGER.debug("Saving Nee-Vo state for %d tank(s)", len(self._state))
        await self._store.async_save(self._state)

    async def async_shutdown(self) -> None:
        """Flush any pending save on unload, then tear down the coordinator."""
        self._save_debouncer.async_cancel()
        # An idempotent final save guarantees the latest meter/ring state is
        # persisted even if a debounced write was still pending.
        await self._async_save()
        await super().async_shutdown()

    async def _async_update_data(self) -> dict[str, NeeVoTankData]:
        """Refresh every tank and compute its derived telemetry."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                await self.api.refresh_tanks()
                tanks: dict[str, Tank] = await self.api.get_tanks_info()
        except InvalidCredentialsError:
            # Try a fresh login once — sessions expire — then re-raise as auth.
            _LOGGER.debug("Nee-Vo session rejected; attempting re-login")
            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    self.api = await NeeVoApiInterface.login(
                        self._email, self._password
                    )
                    tanks = await self.api.get_tanks_info()
                _LOGGER.info("Nee-Vo session expired; re-authenticated successfully")
            except InvalidCredentialsError as relogin_err:
                raise ConfigEntryAuthFailed(
                    translation_domain=DOMAIN,
                    translation_key="invalid_auth",
                ) from relogin_err
            except (GenericHTTPError, ClientError, PyNeeVoError, TimeoutError) as exc:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="cannot_connect",
                    translation_placeholders={"error": str(exc) or type(exc).__name__},
                ) from exc
        except (GenericHTTPError, ClientError, PyNeeVoError, TimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err

        if not tanks:
            # GetAllDisplayPropaneDevices returns inside a finally block, so an
            # HTTP error there yields {} instead of raising; treat an empty map
            # as a transient failure rather than silently dropping all entities.
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="no_tanks",
            )

        _LOGGER.debug("Fetched %d Nee-Vo tank(s) from the cloud", len(tanks))
        now = datetime.now(UTC)
        data: dict[str, NeeVoTankData] = {
            tank_id: self._build_tank_data(tank, now) for tank_id, tank in tanks.items()
        }
        await self._save_debouncer.async_call()
        return data

    def _build_tank_data(self, tank: Tank, now: datetime) -> NeeVoTankData:
        """Build a :class:`NeeVoTankData` and advance the persisted series."""
        level_pct = tank.level
        capacity_l = _coerce_float(tank.tank_capacity)
        level_val = _coerce_float(level_pct)

        # Only derive a liter volume from a physically sane reading: a percent
        # outside 0–100 or a non-positive capacity would otherwise feed a bogus
        # current_l into the consumed meter and the rate ring, corrupting both.
        current_l: float | None = None
        estimated_gal: float | None = None
        if (
            level_val is not None
            and 0 <= level_val <= 100
            and capacity_l is not None
            and capacity_l > 0
        ):
            current_l = level_val / 100.0 * capacity_l
            estimated_gal = round(current_l / LITERS_PER_GALLON, 1)
        elif level_pct is not None or tank.tank_capacity is not None:
            _LOGGER.debug(
                "Tank %s reported out-of-range level=%r capacity=%r; "
                "skipping derived volume",
                tank.id,
                level_pct,
                tank.tank_capacity,
            )

        # _build_tank_data mutates self._state without an explicit lock. That is
        # safe because DataUpdateCoordinator serializes _async_update_data calls
        # (its internal refresh lock), so no two updates ever run concurrently.
        state = self._state.setdefault(tank.id, {})
        consumed_l = self._advance_consumed(state, current_l, now)
        rate = self._advance_rate(state, current_l, now)
        pressure, pressure_unit = _safe_pressure(tank)

        return NeeVoTankData(
            tank_id=tank.id,
            name=tank.name,
            serial=tank.serial_number,
            level_pct=level_pct,
            capacity_l=(
                round(capacity_l, 1)
                if capacity_l is not None and capacity_l > 0
                else None
            ),
            estimated_gal=estimated_gal,
            last_reading=net_date_to_datetime(tank.data.get("LastReadingDate")),
            consumed_l=consumed_l,
            rate_gal_per_day=rate,
            pressure=pressure,
            pressure_unit=pressure_unit,
            raw=tank.data,
        )

    @staticmethod
    def _advance_consumed(
        state: dict[str, Any], current_l: float | None, now: datetime
    ) -> float | None:
        """Advance the forward-only consumed-liters meter.

        Ported from the upstream ``_advance_consumed`` logic but driven by
        successive coordinator observations (no historical series). On the
        first-ever observation we seed ``last_level_l`` and emit nothing for
        consumed (so the recorder never sees a 0→jump spike). On later
        observations, a drop versus the last level is added to the running
        total; refills (upward moves) are ignored, so the total only rises.
        """
        if current_l is None:
            total = state.get("consumed_total_l")
            return round(total, 1) if total is not None else None

        last_level = state.get("last_level_l")
        if last_level is None:
            # First baseline: seed, but publish nothing until a delta exists.
            state["last_level_l"] = current_l
            state["last_ts"] = now.isoformat()
            return None

        total = float(state.get("consumed_total_l", 0.0))
        if current_l < last_level:
            total += last_level - current_l
        state["consumed_total_l"] = round(total, 1)
        state["last_level_l"] = current_l
        state["last_ts"] = now.isoformat()
        return round(total, 1)

    @staticmethod
    def _advance_rate(
        state: dict[str, Any], current_l: float | None, now: datetime
    ) -> float | None:
        """Append to the trailing ring and compute the gal/day rate.

        Maintains a ``≤MAX_RATE_HISTORY_DAYS`` ring of ``(iso, liters)`` and
        returns ``Σ(downward liter steps) / 3.785... / elapsed_days`` over it
        (ported from the upstream ``_window_rate`` downward-step logic). Returns
        ``None`` until at least two readings exist, so it warms up over days.
        """
        if current_l is None:
            return None

        history: list[list[Any]] = state.setdefault("history", [])
        history.append([now.isoformat(), current_l])

        # Parse each row once: drop rows with an unparseable timestamp or a
        # non-numeric liters value, then trim to the trailing window. The
        # surviving (datetime, liters) pairs drive both the persisted ring and
        # the rate, so neither re-parses nor re-validates downstream.
        cutoff = now - timedelta(days=MAX_RATE_HISTORY_DAYS)
        rows: list[tuple[datetime, float]] = []
        for iso, liters in history:
            parsed = _parse_iso(iso)
            value = _coerce_float(liters)
            if parsed is None or value is None:
                _LOGGER.debug("Dropping malformed rate-history row: %r", [iso, liters])
                continue
            if parsed >= cutoff:
                rows.append((parsed, value))

        # Readings arrive in order, but a clock adjustment could reorder them;
        # sort so the downward-step sum and the elapsed span stay correct.
        rows.sort(key=lambda item: item[0])
        # Rewrite the ring from the cleaned, windowed rows (single source of truth).
        history[:] = [[dt.isoformat(), liters] for dt, liters in rows]

        if len(rows) < 2:
            return None

        consumed_l = 0.0
        for (_, prev_l), (_, next_l) in zip(rows, rows[1:], strict=False):
            if next_l < prev_l:
                consumed_l += prev_l - next_l

        elapsed_days = (rows[-1][0] - rows[0][0]).total_seconds() / 86400.0
        if elapsed_days < MIN_RATE_ELAPSED_DAYS:
            return None

        return round(consumed_l / LITERS_PER_GALLON / elapsed_days, 3)


def _parse_iso(value: str) -> datetime | None:
    """Parse a stored ISO timestamp, tolerating malformed ring rows."""
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    """Coerce a value to a finite float, or ``None`` if it cannot be.

    Used at every boundary that ingests untrusted numbers — the live API
    payload and the on-disk Store — so a string, ``None``, or a NaN/inf can
    never propagate into the consumed meter or the rate ring.
    """
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _sanitize_state(stored: Any) -> dict[str, dict[str, Any]]:
    """Validate and normalize persisted state loaded from the Store.

    The Store is on-disk JSON that can be hand-edited, truncated, or carried
    across schema changes, so nothing in it is trusted. Each tank entry is
    rebuilt from only the fields that validate: a non-negative finite
    ``consumed_total_l`` / ``last_level_l``, a string ``last_ts``, and a
    ``history`` of ``[iso_string, finite_float]`` rows. Anything malformed is
    dropped (a bad value re-seeds rather than corrupting the forward-only
    meter), keeping a single trustworthy shape for the rest of the coordinator.
    """
    if not isinstance(stored, dict):
        _LOGGER.warning("Persisted Nee-Vo state is not a mapping; ignoring it")
        return {}

    clean: dict[str, dict[str, Any]] = {}
    for tank_id, raw in stored.items():
        if not isinstance(raw, dict):
            _LOGGER.debug("Dropping non-mapping state for tank %r", tank_id)
            continue
        entry: dict[str, Any] = {}

        for key in ("consumed_total_l", "last_level_l"):
            value = _coerce_float(raw.get(key))
            if value is not None and value >= 0:
                entry[key] = value

        last_ts = raw.get("last_ts")
        if isinstance(last_ts, str) and _parse_iso(last_ts) is not None:
            entry["last_ts"] = last_ts

        history: list[list[Any]] = []
        for row in raw.get("history", []) or []:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                continue
            iso, liters = row
            value = _coerce_float(liters)
            if (
                isinstance(iso, str)
                and _parse_iso(iso) is not None
                and value is not None
            ):
                history.append([iso, value])
        if history:
            entry["history"] = history

        clean[str(tank_id)] = entry
    return clean


def _safe_pressure(tank: Tank) -> tuple[float | None, str | None]:
    """Read optional tank pressure without crashing on a missing field.

    pyneevo's pressure properties do a bare ``dict['Key']`` access, so a device
    payload that omits the pressure fields would raise ``KeyError`` and fail the
    entire update. Pressure is optional diagnostic telemetry, so a missing or
    non-numeric value is treated as absent rather than fatal.
    """
    try:
        raw_pressure = tank.tank_last_pressure
        unit = tank.tank_last_pressure_unit
    except (KeyError, AttributeError):
        return None, None
    try:
        pressure = float(raw_pressure) if raw_pressure is not None else None
    except (TypeError, ValueError):
        return None, unit
    return pressure, unit
