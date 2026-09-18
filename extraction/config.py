CITIES = [
    {"name": "Kigali", "lat": -1.9441, "lon": 30.0619},
    {"name": "Nairobi", "lat": -1.2921, "lon": 36.8219},
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "New York", "lat": 40.7128, "lon": -74.0060},
    {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503},
]

# How many trailing days to (re)fetch on every run. Re-pulling a window instead of
# just "yesterday" makes the extraction idempotent and self-healing if a run is
# missed - no separate state tracking needed for a project this size.
DAYS_BACK = 90
