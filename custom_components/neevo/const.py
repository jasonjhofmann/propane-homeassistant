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

# Manufacturer/model for the per-tank device.
MANUFACTURER = "Otodata"
MODEL = "Nee-Vo Tank Monitor"

ATTRIBUTION = "Tank telemetry by Otodata (Nee-Vo)"
