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
