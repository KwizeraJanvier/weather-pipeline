select
    city,
    date,
    temperature_max_c,
    temperature_min_c,
    temperature_max_c - temperature_min_c as temperature_range_c,
    precipitation_mm,
    precipitation_mm > 0 as is_rain_day,
    windspeed_max_kmh
from {{ ref('stg_weather') }}
