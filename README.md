# Weather & Air Quality Batch Pipeline

A beginner-friendly, fully local data engineering project. It fetches daily
historical weather for a handful of cities, loads it into a Postgres
warehouse, transforms it with dbt, orchestrates the whole thing with Airflow,
and visualizes it with Metabase.

Everything runs natively on macOS via Homebrew + a Python virtualenv — no
Docker.

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
- **Warehouse** — a native Postgres 16 instance (via Homebrew), holding the
  `raw`, `staging`, and `marts` schemas.
- **Transform** (`dbt/weather_dbt`) — dbt models that clean the raw data
  (`stg_weather`) and build an analytics-ready fact table
  (`fct_daily_weather`) with derived columns like temperature range and a
  rain-day flag, landed in the `marts` schema.
- **Orchestration** (`dags/weather_pipeline_dag.py`) — an Airflow DAG (run in
  standalone mode, no containers) that runs extraction, then `dbt run`, once
  a day.
- **Visualization** — [Metabase](https://www.metabase.com/), run as a plain
  `.jar`, pointed at the warehouse, for building a dashboard on top of
  `marts.fct_daily_weather`.

## One-time setup (already done for this machine)

These steps were run once to provision the machine — included here for
reference / for setting this up on another Mac:

```bash
brew install postgresql@16 python@3.12 openjdk
brew services start postgresql@16

# Create the warehouse role + database
psql -U "$(whoami)" -d postgres -c "CREATE ROLE warehouse LOGIN PASSWORD 'warehouse';"
psql -U "$(whoami)" -d postgres -c "CREATE DATABASE warehouse OWNER warehouse;"
psql "postgresql://warehouse:warehouse@localhost:5432/warehouse" -f sql/init_warehouse_schemas.sql

# Project virtualenv with Airflow + dbt
python3.12 -m venv .venv
AIRFLOW_VERSION=2.9.3
PYTHON_VERSION=3.12
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
.venv/bin/pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}" \
    "dbt-core==1.8.*" "dbt-postgres==1.8.*" "requests==2.32.3" "psycopg2-binary==2.9.9"

# dbt profile (local only, not committed)
cp dbt/weather_dbt/profiles.yml.example dbt/weather_dbt/profiles.yml

# Airflow metadata db, pointed at this project's dags/ folder
export AIRFLOW_HOME="$(pwd)/airflow_home"
.venv/bin/airflow db migrate
# then edit airflow_home/airflow.cfg: dags_folder -> this project's dags/ folder,
# load_examples -> False (already done on this machine)

# Metabase jar (~660MB download from downloads.metabase.com)
mkdir -p metabase
curl -L -o metabase/metabase.jar "https://downloads.metabase.com/latest/metabase.jar"
```

> Note on dbt versions: newer `dbt-core` releases (2.x) moved Postgres to an
> experimental adapter tier. This project pins `dbt-core`/`dbt-postgres` to
> the `1.8.x` line, which fully supports Postgres.

## Everyday use

### 1. Make sure Postgres is running

```bash
brew services list   # should show postgresql@16 as "started"
```

### 2. Run Airflow (webserver + scheduler in one process)

```bash
cd "/Users/janvier/Data Engineer Project"
export AIRFLOW_HOME="$(pwd)/airflow_home"
.venv/bin/airflow standalone
```

First run prints an auto-generated admin password to the terminal — note it
down. Leave this running in its own terminal tab; open
[localhost:8080](http://localhost:8080), log in, unpause `weather_pipeline`,
and trigger it manually to run it now (it's also scheduled `@daily`).

### 3. Run Metabase

```bash
cd "/Users/janvier/Data Engineer Project/metabase"
/opt/homebrew/opt/openjdk/bin/java -jar metabase.jar
```

First run takes a minute or two to initialize its own internal app database.
Open [localhost:3000](http://localhost:3000), finish the one-time setup, and
add a Postgres connection:

- Host: `localhost`, Port: `5432`, Database: `warehouse`
- User: `warehouse`, Password: `warehouse`

Then build a dashboard/questions on top of the `marts.fct_daily_weather`
table — e.g. average max temp by city over time, or rainy days per month.

## Running dbt manually (outside Airflow)

Useful while developing models, so you don't have to re-trigger the whole
DAG every time.

```bash
cd dbt/weather_dbt
../../.venv/bin/dbt run --profiles-dir .
../../.venv/bin/dbt test --profiles-dir .
```

## Running extraction manually

```bash
cd extraction
../.venv/bin/python fetch_weather.py
```

## Next steps / ideas to extend this

- Add more cities, or swap in a different data source entirely.
- Add more dbt tests (e.g. `accepted_values`, custom singular tests for
  physically implausible values).
- Add a retry/backoff policy in the DAG to handle API outages gracefully.
- Swap Metabase for Superset, or add a Streamlit app for a custom dashboard.
- Move the warehouse to a free-tier cloud Postgres (e.g. Supabase, Neon) and
  Airflow to a small VM, once you're ready to go beyond local.

## Stopping / resetting

```bash
# Stop Airflow: Ctrl+C in its terminal
# Stop Metabase: Ctrl+C in its terminal
brew services stop postgresql@16   # stop Postgres (data persists)
```

To fully reset the warehouse data:

```bash
psql -U "$(whoami)" -d postgres -c "DROP DATABASE warehouse;"
psql -U "$(whoami)" -d postgres -c "CREATE DATABASE warehouse OWNER warehouse;"
psql "postgresql://warehouse:warehouse@localhost:5432/warehouse" -f sql/init_warehouse_schemas.sql
```
