# Weather & Air Quality Batch Pipeline

A beginner-friendly, fully local data engineering project. It fetches daily
historical weather for a handful of cities, loads it into a Postgres
warehouse, transforms it with dbt, orchestrates the whole thing with Airflow,
and visualizes it with Metabase.

## Architecture

```
Open-Meteo API --> extraction/fetch_weather.py --> raw.weather_daily (Postgres)
                                                          |
                                                          v
                                            dbt: staging.stg_weather (view)
                                                          |
                                                          v
                                            dbt: marts.fct_daily_weather (table)
                                                          |
                                                          v
                                                      Metabase dashboard

Airflow DAG "weather_pipeline" runs extraction --> dbt run, daily.
```

- **Extraction** (`extraction/fetch_weather.py`) — pulls the trailing 90 days
  of daily weather (max/min temp, precipitation, wind) per city from
  [Open-Meteo](https://open-meteo.com/) (no API key needed) and upserts it
  into `raw.weather_daily`.
- **Warehouse** — a single Postgres instance. It also hosts Airflow's own
  metadata in a separate database (`airflow_meta`) so you only run one
  Postgres container.
- **Transform** (`dbt/weather_dbt`) — dbt models that clean the raw data
  (`stg_weather`) and build an analytics-ready fact table
  (`fct_daily_weather`) with derived columns like temperature range and a
  rain-day flag.
- **Orchestration** (`dags/weather_pipeline_dag.py`) — an Airflow DAG that
  runs extraction, then `dbt run`, once a day.
- **Visualization** — [Metabase](https://www.metabase.com/), pointed at the
  warehouse, for building a dashboard on top of `marts.fct_daily_weather`.

## Prerequisites

- Docker and Docker Compose
- ~4GB of free RAM for the containers (Postgres + Airflow x3 + Metabase)

## Setup

1. Copy the env file and adjust if you want (defaults work as-is):

   ```bash
   cp .env.example .env
   ```

2. Build the images (this installs dbt and the extraction script's Python
   deps into the Airflow image):

   ```bash
   docker compose build
   ```

3. Initialize Airflow's metadata DB and admin user:

   ```bash
   docker compose up airflow-init
   ```

4. Start everything:

   ```bash
   docker compose up -d
   ```

5. Open the Airflow UI at [localhost:8080](http://localhost:8080)
   (username/password: `admin` / `admin`, or whatever you set in `.env`).
   Unpause the `weather_pipeline` DAG and trigger it manually the first time.

6. Once the DAG run finishes (extraction + `dbt run`), open Metabase at
   [localhost:3000](http://localhost:3000), finish its one-time setup, and
   add a Postgres database connection pointing at:

   - Host: `postgres` (if adding it from within the Docker network — Metabase
     is on the same `docker compose` network) or `localhost` if you configure
     it from your host machine's browser and expose the port differently.
     Simplest: host `postgres`, port `5432`, database `warehouse`, user/pass
     from your `.env`.

7. Build a dashboard/questions on top of the `marts.fct_daily_weather` table
   — e.g. average max temp by city over time, or rainy days per month.

## Running dbt manually (outside Airflow)

Useful while developing models, so you don't have to re-trigger the whole
DAG every time.

```bash
cd dbt/weather_dbt
cp profiles.yml.example profiles.yml
pip install dbt-postgres
export WAREHOUSE_DB_HOST=localhost WAREHOUSE_DB_PORT=5432 \
       WAREHOUSE_DB_NAME=warehouse WAREHOUSE_DB_USER=warehouse WAREHOUSE_DB_PASSWORD=warehouse
dbt run
dbt test
```

## Running extraction manually

```bash
cd extraction
pip install -r requirements.txt
export WAREHOUSE_DB_HOST=localhost WAREHOUSE_DB_PORT=5432 \
       WAREHOUSE_DB_NAME=warehouse WAREHOUSE_DB_USER=warehouse WAREHOUSE_DB_PASSWORD=warehouse
python fetch_weather.py
```

## Next steps / ideas to extend this

- Add more cities, or swap in a different data source entirely.
- Add more dbt tests (e.g. `accepted_values`, custom singular tests for
  physically implausible values).
- Add a `WeatherApiSensor`/retry policy in the DAG to handle API outages
  gracefully.
- Swap Metabase for Superset, or add a Streamlit app for a custom dashboard.
- Move the warehouse to a free-tier cloud Postgres (e.g. Supabase, Neon) and
  Airflow to a small VM, once you're ready to go beyond local.

## Stopping / resetting

```bash
docker compose down          # stop containers, keep data
docker compose down -v       # stop containers and wipe volumes (fresh start)
```
