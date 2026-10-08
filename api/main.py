from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from db import query

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Weather Pipeline API")


@app.get("/api/health")
def health():
    query("SELECT 1")
    return {"status": "ok"}


@app.get("/api/cities")
def list_cities():
    rows = query("SELECT DISTINCT city FROM marts.fct_daily_weather ORDER BY city")
    return [row["city"] for row in rows]


@app.get("/api/weather/{city}")
def city_weather(city: str, days: int = 30):
    rows = query(
        """
        SELECT date, temperature_max_c, temperature_min_c, precipitation_mm,
               windspeed_max_kmh, is_rain_day
        FROM marts.fct_daily_weather
        WHERE city = %s AND date >= current_date - %s::int
        ORDER BY date
        """,
        (city, days),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for city '{city}'")
    return rows


@app.get("/api/forecast/{city}")
def city_forecast(city: str):
    # marts.weather_forecast accumulates every past prediction it's ever made
    # (upserted, never deleted) so old forecasts for dates long since realized
    # stick around as a record of "what we predicted back then." For the
    # dashboard we only want the current, forward-looking forecast.
    return query(
        """
        SELECT date, predicted_temp_max_c, predicted_precip_mm
        FROM marts.weather_forecast
        WHERE city = %s AND date >= current_date
        ORDER BY date
        """,
        (city,),
    )


@app.get("/api/rain-stats")
def rain_stats():
    return query(
        """
        SELECT
            city,
            count(*) FILTER (WHERE is_rain_day) AS rain_days,
            count(*) AS total_days,
            round(100.0 * count(*) FILTER (WHERE is_rain_day) / count(*), 1) AS rain_pct,
            round(avg(temperature_max_c) FILTER (WHERE is_rain_day), 1) AS avg_temp_rain_day,
            round(avg(temperature_max_c) FILTER (WHERE NOT is_rain_day), 1) AS avg_temp_non_rain_day
        FROM marts.fct_daily_weather
        GROUP BY city
        ORDER BY city
        """
    )


# Must be mounted last - it's a catch-all for "/" and would otherwise shadow
# the /api/* routes above.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
