select
    city,
    date,
    temperature_max_c,
    temperature_min_c,
    precipitation_mm,
    windspeed_max_kmh,
    loaded_at
from {{ source('raw', 'weather_daily') }}
