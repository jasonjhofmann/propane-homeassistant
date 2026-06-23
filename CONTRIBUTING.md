# Contributing

## Architecture (5-minute tour)

```
custom_components/neevo/
  __init__.py      Entry setup/unload: pyneevo login, build the coordinator,
                   load the Store, first refresh, forward to the sensor platform.
  config_flow.py   User flow (email + password) + reauth (password only). Each
                   validates by a live pyneevo login + get_tanks_info().
  coordinator.py   One DataUpdateCoordinator for the whole account. refresh_tanks()
                   every 6 hours; builds a NeeVoTankData per tank and advances the
                   persisted forward-only consumed-liters meter + the gal/day rate
                   ring. Ports the .NET /Date(ms)/ parser and the downward-step
                   consumption logic from the original pyscript implementation.
  entity.py        Base entity: one device per tank (DeviceInfo identifiers =
                   {(DOMAIN, tank.id)}), has_entity_name.
  sensor.py        SensorEntityDescription list; unique_id = {tank_id}_{key}.
  diagnostics.py   Config-entry diagnostics (credentials/serial/id/address redacted).
  brand/           Brand assets — generated, do not hand-edit; see scripts/.
  quality_scale.yaml  Self-assessment vs the core quality scale (target: Gold).
```

Key invariants:

- **The account email is the entry's identity** (`unique_id`); the only mutable
  field is the password, handled by reauth.
- **The consumed meter is forward-only** — a drop in liters is added to the
  running total; refills (upward moves) are ignored; the first observation seeds
  a baseline and publishes nothing, so the recorder never sees a 0→jump spike.
  Do not backfill it.
- **`strings.json` and `translations/en.json` are kept identical** (copy on
  every change).
- **No real identifiers** anywhere — synthetic emails/serials/tank IDs only.

## Development setup

```sh
uv venv .venv && uv pip install -p .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest tests -q --cov=custom_components.neevo   # >=95%
.venv/bin/python -m mypy --strict custom_components/neevo/
.venv/bin/python -m ruff check custom_components tests scripts
.venv/bin/python -m ruff format --check custom_components tests scripts
```

CI enforces all of these plus hassfest and HACS validation, on a Python
3.13/3.14 matrix. Live smoke test against the real API:

```sh
NEEVO_EMAIL=... NEEVO_PASSWORD=... python3 scripts/smoke_test.py
```

Brand assets regenerate with `python3 scripts/generate_brand.py` (Pillow).

## Making a release

1. Update `CHANGELOG.md` and bump `version` in `manifest.json` (manifest keys
   must stay sorted: `domain`, `name`, then alphabetical — hassfest enforces).
2. Commit, push, and wait for the Validate workflow to go **green**.
3. Tag and create the GitHub release **after** the green run.
