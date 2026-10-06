"""Pull daily historical weather for a set of cities from Open-Meteo (no API key
required) and upsert it into the raw.weather_daily table in the warehouse.
"""
import multiprocessing
import os
from datetime import date, timedelta

import psycopg2
import requests

from config import CITIES, DAYS_BACK

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
RUN_TIMEOUT_SECONDS = 120

# trust_env=False stops requests from checking the OS for proxy settings on
# every call. On macOS that check (via _scproxy/cfprefsd) can hang forever
# when run from a subprocess spawned by Airflow, pegging a CPU core
# indefinitely instead of erroring out - this project has no proxy to honor
# anyway, so skip the lookup entirely.
SESSION = requests.Session()
SESSION.trust_env = False


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("WAREHOUSE_DB_HOST", "localhost"),
        port=os.environ.get("WAREHOUSE_DB_PORT", "5432"),
        dbname=os.environ.get("WAREHOUSE_DB_NAME", "warehouse"),
        user=os.environ.get("WAREHOUSE_DB_USER", "warehouse"),
        password=os.environ.get("WAREHOUSE_DB_PASSWORD", "warehouse"),
        # We never use Kerberos/GSSAPI auth, but libpq probes for a GSS
        # credential cache before every connection unless told not to. On
        # this macOS version that probe can hang forever (same cfprefsd
        # flakiness as the requests proxy-lookup hang above), pegging a CPU
        # core indefinitely instead of erroring out. Skip the probe entirely.
        gssencmode="disable",
    )


def fetch_city_weather(lat: float, lon: float, days_back: int) -> list[dict]:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back)

    response = SESSION.get(
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


def _run_impl() -> None:
    conn = get_connection()
    try:
        for city in CITIES:
            rows = fetch_city_weather(city["lat"], city["lon"], DAYS_BACK)
            upsert_readings(conn, city["name"], rows)
            print(f"{city['name']}: upserted {len(rows)} rows")
    finally:
        conn.close()


def run() -> None:
    """Run extraction in a subprocess with a hard wall-clock budget.

    On this macOS version, certain system calls (requests' proxy lookup,
    libpq's GSSAPI credential probe, likely others we haven't hit yet) can
    hang forever inside a macOS system daemon (cfprefsd) in a way that does
    NOT respond to Python signals (signal.alarm never fires - the hang is in
    a non-interruptible Mach IPC call). The only thing that reliably stops
    it, observed repeatedly in production use, is SIGKILL from outside the
    process. Running the real work in a subprocess lets us do exactly that:
    if it doesn't finish within RUN_TIMEOUT_SECONDS, kill it and fail the
    task so Airflow retries, instead of blocking the pipeline for hours.
    """
    proc = multiprocessing.Process(target=_run_impl)
    proc.start()
    proc.join(RUN_TIMEOUT_SECONDS)
    if proc.is_alive():
        proc.kill()
        proc.join()
        raise TimeoutError(
            f"extraction hung for over {RUN_TIMEOUT_SECONDS}s (likely the macOS "
            "cfprefsd hang - see README) and was killed; Airflow should retry"
        )
    if proc.exitcode != 0:
        raise RuntimeError(f"extraction subprocess failed with exit code {proc.exitcode}")


if __name__ == "__main__":
    run()
