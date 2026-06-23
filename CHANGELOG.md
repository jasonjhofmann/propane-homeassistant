# Changelog

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
  pressure sensor.
- Forward-only consumed-liters meter and a ≤30-day rate ring, both persisted to
  a per-entry `Store` (debounced save, flushed on unload) so they survive
  restarts. Both warm up over successive polls — `pyneevo` exposes no historical
  level series.
- Diagnostics with credentials, serials, tank IDs, and address fields redacted.
- In-tree original brand artwork (`scripts/generate_brand.py`).
- CI: hassfest, HACS, ruff (check + format), mypy strict, and a pytest 3.13/3.14
  matrix with `--cov-fail-under=95`.
