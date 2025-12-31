"""Constants for the NSW Fuel Station App."""

# Data key for fuel station coordinator
DATA_NSW_FUEL_STATION = "nsw_fuel_station"

# Allowed fuel types
ALLOWED_FUEL_TYPES = [
    "E10",
    "U91",
    "E85",
    "P95",
    "P98",
    "DL",
    "PDL",
    "B20",
    "LPG",
    "CNG",
    "EV",
]

# Default configuration values
DEFAULT_POLL_INTERVAL = 60  # minutes
DEFAULT_LOG_LEVEL = "INFO"
