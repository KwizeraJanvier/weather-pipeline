"""Pull daily historical weather for a set of cities from Open-Meteo (no API key
required) and upsert it into the raw.weather_daily table in the warehouse.
"""
import os
from datetime import date, timedelta

import psycopg2
import requests

from config import CITIES, DAYS_BACK

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("WAREHOUSE_DB_HOST", "localhost"),
        port=os.environ.get("WAREHOUSE_DB_PORT", "5432"),
        dbname=os.environ.get("WAREHOUSE_DB_NAME", "warehouse"),
        user=os.environ.get("WAREHOUSE_DB_USER", "warehouse"),
        password=os.environ.get("WAREHOUSE_DB_PASSWORD", "warehouse"),
    )


def fetch_city_weather(lat: float, lon: float, days_back: int) -> list[dict]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back)

    response = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
            "timezone": "auto",
        },
        timeout=30,
    )
    response.raise_for_status()
    daily = response.json()["daily"]

    return [
        {
            "date": daily["time"][i],
            "temperature_max_c": daily["temperature_2m_max"][i],
            "temperature_min_c": daily["temperature_2m_min"][i],
            "precipitation_mm": daily["precipitation_sum"][i],
            "windspeed_max_kmh": daily["windspeed_10m_max"][i],
        }
        for i in range(len(daily["time"]))
    ]


def upsert_readings(conn, city: str, rows: list[dict]) -> None:
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO raw.weather_daily
                    (city, date, temperature_max_c, temperature_min_c, precipitation_mm, windspeed_max_kmh)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (city, date) DO UPDATE SET
                    temperature_max_c = EXCLUDED.temperature_max_c,
                    temperature_min_c = EXCLUDED.temperature_min_c,
                    precipitation_mm = EXCLUDED.precipitation_mm,
                    windspeed_max_kmh = EXCLUDED.windspeed_max_kmh,
                    loaded_at = now()
                """,
                (
                    city,
                    row["date"],
                    row["temperature_max_c"],
                    row["temperature_min_c"],
                    row["precipitation_mm"],
                    row["windspeed_max_kmh"],
                ),
            )
    conn.commit()


def run() -> None:
    conn = get_connection()
    try:
        for city in CITIES:
            rows = fetch_city_weather(city["lat"], city["lon"], DAYS_BACK)
            upsert_readings(conn, city["name"], rows)
            print(f"{city['name']}: upserted {len(rows)} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
