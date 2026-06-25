# Nee-Vo

[![GitHub release](https://img.shields.io/github/v/release/jasonjhofmann/propane-homeassistant?include_prereleases)](https://github.com/jasonjhofmann/propane-homeassistant/releases)
[![Validate](https://github.com/jasonjhofmann/propane-homeassistant/actions/workflows/validate.yml/badge.svg)](https://github.com/jasonjhofmann/propane-homeassistant/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/github/license/jasonjhofmann/propane-homeassistant)](LICENSE)

Home Assistant integration for **Nee-Vo propane tank monitors** (Otodata
TM-series remote tank gauges). It reads your tank level, estimated volume, last
telemetry time, and a derived consumption rate, and exposes a cumulative
gas-consumption meter you can wire into the Energy dashboard.

## What it is

[Nee-Vo](https://nee-vo.com/) is the consumer app for Otodata's TM-series
cellular tank monitors — small devices that clip onto a propane tank's dial
gauge and report the level to the cloud. The same hardware/platform is
**white-labeled across many propane suppliers**, so if your supplier's app or
portal is "Nee-Vo powered" (or you use the Nee-Vo app directly), this
integration works with your account.

It depends on the community [`pyneevo`](https://pypi.org/project/pyneevo/)
library and polls the Nee-Vo cloud directly.

## Installation

Until this repo is in the HACS default store, add it as a custom repository:

1. HACS → ⋮ → *Custom repositories* → add
   `https://github.com/jasonjhofmann/propane-homeassistant` (type: Integration).
2. Install **Nee-Vo** and restart Home Assistant.

## Configuration

Settings → Devices & Services → Add Integration → **Nee-Vo**.

Enter the **email** and **password** for your Nee-Vo account (the same ones you
use in the app). The integration logs in, confirms at least one tank is on the
account, and creates one device per tank.

| Parameter | Description |
| --- | --- |
| Email | Your Nee-Vo (Otodata) account email |
| Password | Your Nee-Vo account password (stored only to refresh readings) |

### Options

There is no options flow. Polling is fixed at **6 hours** — Otodata telemetry
updates roughly once per day, so a few polls a day catches the new read without
hammering the cloud. If your password is rejected, Home Assistant prompts for
reauthentication automatically.

## Entities

One device per tank, with these sensors:

| Entity | Unit | Device class | Notes |
| --- | --- | --- | --- |
| Tank level | % | — | Reported fill level |
| Estimated volume | gal | Volume storage | Level × tank capacity, converted from liters |
| Last reading | — | Timestamp | When the monitor last reported |
| Consumption rate | gal/d | — | Trailing downward-step rate; warms up over days |
| Consumed | L | Gas | Cumulative consumption (Energy dashboard) |
| Pressure | (from device) | Pressure | Diagnostic; only if the monitor reports pressure |

The **Pressure** sensor's unit is mapped from what the monitor reports (`psi`,
`psig`, `kpa`, `bar`, `mbar`, `hpa`). If a monitor reports an unrecognized unit
string, the sensor still appears but without a unit of measurement.

The **Consumed** sensor is a forward-only `total_increasing` meter: each poll it
adds any drop in the tank's liter level to a running total (refills are
ignored), so it only ever rises. It is persisted across restarts. On a fresh
install it reads `unknown` until a second poll provides a level to compare
against (see *Known limitations*).

## Energy dashboard wiring

Home Assistant's **gas** source needs a cumulative meter in a volume unit:

1. Settings → Dashboards → Energy → *Add gas source*.
2. Pick **Consumed** (`sensor.<tank>_consumed`, in L) as the consumption entity.
3. Optionally set a price per unit to track cost (cost accrues forward from when
   the price is set).

The **Consumption rate** sensor (gal/day) is informational and is not a valid
Energy consumption entity on its own.

## Examples

Notify when the tank drops below 20%:

```yaml
automation:
  - alias: "Propane low"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.my_tank_tank_level
        below: 20
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "Propane low"
          message: "Tank at {{ states('sensor.my_tank_tank_level') }}% — time to schedule a fill."
```

## Known limitations

- **The consumption rate warms up over days.** `pyneevo` exposes only the
  *current* reading, not a historical level series, so the gal/day rate is built
  from successive polls and reports `unknown` until at least two readings exist.
  It becomes meaningful after a few days of polling.
- **No historical backfill.** For the same reason, the consumed meter and the
  rate start from when the integration is installed; there is no way to import
  past usage.
- **One Home Assistant account per Nee-Vo login.** The config entry is keyed on
  the account email; all tanks under that login are created as devices on the
  single entry.
- **Integer-percent resolution.** The level is reported as a whole percent, so
  the consumed meter steps in level-quantized chunks rather than continuously.

## Troubleshooting

- **"Invalid authentication" during setup** — the email or password is wrong;
  confirm them in the Nee-Vo app first.
- **"No propane tanks were found"** — the login succeeded but the account has no
  monitors associated with it.
- **Entities `unavailable`** — the monitor missed its last cloud check-in
  (cellular monitors report intermittently); the integration recovers on the
  next successful poll.
- **All entities `unavailable` after working before** — if every monitor has
  been removed from your Nee-Vo account, the integration has no tanks to report
  and marks all entities unavailable; they return on the next poll once at least
  one monitor is back on the account.
- **Download diagnostics** (integration page → ⋮ → Download diagnostics) to see
  each tank's last telemetry and the update health — credentials, serials, tank
  IDs, and any address fields are redacted.

## Removal

1. Settings → Devices & Services → **Nee-Vo** → delete the config entry (its
   devices and entities are removed automatically).
2. Uninstall the integration from HACS and restart Home Assistant.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) — architecture tour, dev setup, and the
quality gates (pytest+coverage, mypy strict, ruff).

```sh
pip install -r requirements_test.txt
pytest tests -q --cov=custom_components.neevo
NEEVO_EMAIL=... NEEVO_PASSWORD=... python3 scripts/smoke_test.py
```

## Disclaimer

This is an **unofficial** integration. It is **not affiliated with, endorsed
by, or supported by** Nee-Vo, Otodata, or any propane supplier. It uses the
community `pyneevo` library. "Nee-Vo" and "Otodata" are trademarks of their
respective owners. All examples in this repository use synthetic identifiers.
