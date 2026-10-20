# Changelog

## 0.1.3 — 2026-10-20

- **README: when entities go `unavailable`.** It said a missed cloud
  check-in makes them unavailable. In fact only a failed poll (connection
  error, timeout, no tanks returned) or a tank leaving the account does; a
  monitor that missed a check-in stays available with its previous values.
  HACS shows the README from the latest release, which is why this ships as
  one. No integration code changes.

## 0.1.2 — 2026-10-18

- **Tests: device lookups work on every harness CI resolves.** The weekly
  Validate run had failed since 2026-08-31: HA dev hard-errors the deprecated
  `async_get_device` in test frames. A `_get_device` helper uses
  `async_get_device_by_identifier` where the harness has it (HA 2026.8+) and
  falls back on the older harness the Python 3.13 leg resolves. No integration
  code changes; the integration itself never called the old API.
- **CI: new Minimum supported HA job.** It reads the floor from `hacs.json`
  and the integration's requirements from `manifest.json`, resolves every
  package as of the floor's release date and restates HA's own exact pins (a
  fresh resolve of HA 2025.6 pulls a `pycares` too new for its `aiodns` and
  fails to import), and imports every module against that exact release. It is
  now the only mypy run: HA 2026.9 moved core from voluptuous to probatio, and
  HA 2026.10 retyped schema arguments to match, so the lint job's mypy step
  against the newest HA had failed since early October on the voluptuous
  schemas older releases need. Typing only: HA still accepts voluptuous
  schemas at runtime, and the tests job still runs on the newest HA.
- **`hacs.json`: declare `country: ["US", "CA"]`.** Nee-Vo / Otodata tank
  monitors are sold and supported in the US and Canada, and the HACS default
  store expects region-locked services to declare their countries (the
  airnow-station submission was bounced for omitting exactly this). No code
  change.

## 0.1.1 — 2026-06-25

Hardening release — no behavior change for healthy accounts; all fixes are
defensive. Output of a full-repo review.

- **Robust `.NET` date parsing.** The `/Date(ms±tz)/` regex now anchors the full
  epoch token, so a corrupt payload like `/Date(123abc)/` is rejected instead of
  silently yielding a 1970-era timestamp, and an out-of-range epoch returns
  `None` instead of crashing the poll with `ValueError`.
- **Persisted state is validated on load.** The per-entry `Store` is treated as
  untrusted: a non-numeric/NaN/negative total, a malformed timestamp, or a
  bad history row is dropped (re-seeding) rather than crashing a later refresh.
- **Tank-reading bounds checks.** A level outside 0–100 % or a non-positive
  capacity no longer feeds a bogus liter volume into the consumed meter or rate.
- **Rate ring.** Parses each history row once (no double-parse), and rejects a
  rate computed over a sub-minute window (which could divide a real delta by a
  near-zero elapsed time and emit an absurd spike).
- **Timeouts.** Config-entry setup login and each coordinator poll are wrapped in
  a hard request timeout so a stalled connection can't hang HA startup.
- **Debug/diagnostic logging** added on the poll, session-relogin, Store, and
  parse paths (previously the integration emitted no logs of its own).
- **Icons** are now sourced solely from `icons.json` (removed the duplicate
  `icon=` on three sensor descriptions, eliminating drift).
- Docs: README notes the all-tanks-removed unavailable case, unsupported
  pressure-unit behavior, and the first-poll `unknown` consumed reading.

## 0.1.0 — 2026-06-23

Initial release. Gold quality-scale target.

- Config flow: email + password, validated by a live `pyneevo` login plus a
  non-empty `get_tanks_info()`; unique ID = lowercased account email.
- Reauthentication flow on rejected credentials (re-enter password only).
- 6-hour `DataUpdateCoordinator` over `pyneevo`; an unexpectedly empty tank map
  (a known `GetAllDisplayPropaneDevices` quirk) is treated as `UpdateFailed`,
  and `InvalidCredentialsError` raises `ConfigEntryAuthFailed`.
- One device per tank, with sensors: tank level (%), estimated volume (gal),
  last reading (timestamp), consumption rate (gal/day), consumed (L,
  `total_increasing`, for the Energy dashboard), and an optional diagnostic
  pressure sensor. The device `serial_number` is coerced to a string, since
  `pyneevo` returns it as an int (which the device registry rejects — a hard
  error from HA 2026.12.0).
- Forward-only consumed-liters meter and a ≤30-day rate ring, both persisted to
  a per-entry `Store` (debounced save, flushed on unload) so they survive
  restarts. Both warm up over successive polls — `pyneevo` exposes no historical
  level series.
- Diagnostics with credentials, serials, tank IDs, and address fields redacted.
- In-tree original brand artwork (`scripts/generate_brand.py`).
- CI: hassfest, HACS, ruff (check + format), mypy strict, and a pytest 3.13/3.14
  matrix with `--cov-fail-under=95`.
