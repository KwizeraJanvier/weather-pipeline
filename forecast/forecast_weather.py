"""Fit a simple per-city linear trend over the trailing LOOKBACK_DAYS of
actuals in marts.fct_daily_weather, project it FORECAST_DAYS forward, and
upsert the predictions into marts.weather_forecast.

This is deliberately simple (a straight-line fit, not a real ML model) - it's
meant to give Metabase something to chart alongside the actuals, not to be
an accurate weather forecaster.
"""
import os
from datetime import date, timedelta

import numpy as np
import psycopg2

LOOKBACK_DAYS = 30
FORECAST_DAYS = 7


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("WAREHOUSE_DB_HOST", "localhost"),
        port=os.environ.get("WAREHOUSE_DB_PORT", "5432"),
        dbname=os.environ.get("WAREHOUSE_DB_NAME", "warehouse"),
        user=os.environ.get("WAREHOUSE_DB_USER", "warehouse"),
        password=os.environ.get("WAREHOUSE_DB_PASSWORD", "warehouse"),
    )


def fetch_cities(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT city FROM marts.fct_daily_weather ORDER BY city;")
        return [row[0] for row in cur.fetchall()]


def fetch_recent_actuals(conn, city: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, temperature_max_c, precipitation_mm
            FROM marts.fct_daily_weather
            WHERE city = %s AND date >= %s
            ORDER BY date
            """,
            (city, date.today() - timedelta(days=LOOKBACK_DAYS)),
        )
        return cur.fetchall()


def fit_and_project(rows: list[tuple]) -> list[dict]:
    if len(rows) < 2:
        return []

    x = np.array([row[0].toordinal() for row in rows], dtype=float)
    temp_y = np.array([row[1] for row in rows], dtype=float)
    precip_y = np.array([row[2] for row in rows], dtype=float)

    temp_slope, temp_intercept = np.polyfit(x, temp_y, 1)
    precip_slope, precip_intercept = np.polyfit(x, precip_y, 1)

    last_date = rows[-1][0]
    predictions = []
    for i in range(1, FORECAST_DAYS + 1):
        future_date = last_date + timedelta(days=i)
        future_x = future_date.toordinal()
        predicted_temp = temp_slope * future_x + temp_intercept
        predicted_precip = max(0.0, precip_slope * future_x + precip_intercept)
        predictions.append(
            {
                "date": future_date,
                "predicted_temp_max_c": round(float(predicted_temp), 2),
                "predicted_precip_mm": round(float(predicted_precip), 2),
            }
        )
    return predictions


def upsert_forecast(conn, city: str, predictions: list[dict]) -> None:
    with conn.cursor() as cur:
        for pred in predictions:
            cur.execute(
                """
                INSERT INTO marts.weather_forecast
                    (city, date, predicted_temp_max_c, predicted_precip_mm)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (city, date) DO UPDATE SET
                    predicted_temp_max_c = EXCLUDED.predicted_temp_max_c,
                    predicted_precip_mm = EXCLUDED.predicted_precip_mm,
                    generated_at = now()
                """,
                (city, pred["date"], pred["predicted_temp_max_c"], pred["predicted_precip_mm"]),
            )
    conn.commit()


def run() -> None:
    conn = get_connection()
    try:
        for city in fetch_cities(conn):
            rows = fetch_recent_actuals(conn, city)
            predictions = fit_and_project(rows)
            if not predictions:
                print(f"{city}: not enough history to forecast, skipped")
                continue
            upsert_forecast(conn, city, predictions)
            print(f"{city}: wrote {len(predictions)} forecast rows")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
