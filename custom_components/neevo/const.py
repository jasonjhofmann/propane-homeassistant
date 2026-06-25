"""Constants for the Nee-Vo integration."""

from datetime import timedelta

DOMAIN = "neevo"

# Otodata tank telemetry refreshes roughly once per day; poll a few times a day
# so a missed read is caught the same day without hammering the cloud API.
UPDATE_INTERVAL = timedelta(hours=6)

# Liters per US gallon (exact). Otodata reports TankCapacity in liters.
LITERS_PER_GALLON = 3.785411784

# Storage schema version for the per-entry consumed-meter / rate-ring Store.
STORAGE_VERSION = 1

# Cap the persisted (timestamp, liters) ring used to derive the gal/day rate.
MAX_RATE_HISTORY_DAYS = 30

# Reject a gal/day rate computed over a window shorter than this: two readings
# captured seconds apart (e.g. a manual reload right after a poll) would divide
# a real liter delta by a near-zero elapsed time and emit an absurd spike.
MIN_RATE_ELAPSED_DAYS = 60.0 / 86400.0  # 1 minute

# Hard timeout (seconds) for a single Nee-Vo cloud call. pyneevo's aiohttp
# requests carry no explicit timeout, so without this a stalled-but-not-closed
# connection could hang config-entry setup or a coordinator poll indefinitely.
REQUEST_TIMEOUT = 60

# Manufacturer/model for the per-tank device.
MANUFACTURER = "Otodata"
MODEL = "Nee-Vo Tank Monitor"

ATTRIBUTION = "Tank telemetry by Otodata (Nee-Vo)"
