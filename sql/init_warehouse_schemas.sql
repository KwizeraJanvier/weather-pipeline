-- Runs against the warehouse database (POSTGRES_DB).
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;

CREATE TABLE IF NOT EXISTS raw.weather_daily (
    city TEXT NOT NULL,
    date DATE NOT NULL,
    temperature_max_c NUMERIC,
    temperature_min_c NUMERIC,
    precipitation_mm NUMERIC,
    windspeed_max_kmh NUMERIC,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (city, date)
);

-- Populated by forecast/forecast_weather.py (not dbt) - a simple per-city
-- linear trend projected a few days forward, refreshed daily. Past forecast
-- rows are never overwritten, only future ones, so over time this also
-- doubles as a record of "what did we predict N days ago for this date",
-- comparable against marts.fct_daily_weather once that date has actuals.
CREATE TABLE IF NOT EXISTS marts.weather_forecast (
    city TEXT NOT NULL,
    date DATE NOT NULL,
    predicted_temp_max_c NUMERIC,
    predicted_precip_mm NUMERIC,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (city, date)
);
