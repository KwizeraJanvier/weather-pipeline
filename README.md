# Weather Batch Pipeline

A beginner-friendly, fully local data engineering project. Every day it:

1. **Extracts** daily historical weather for five cities from the free
   [Open-Meteo](https://open-meteo.com/) API (no API key needed),
2. **Loads** it into a Postgres warehouse,
3. **Transforms** it into an analytics-ready table with dbt,
4. **Forecasts** the next 7 days per city with a simple trend model,
5. **Orchestrates** all of the above with Airflow, and
6. **Visualizes** actuals and forecasts in Metabase.

Everything runs natively on macOS via Homebrew + a Python virtualenv. No
Docker (it was dropped for privacy reasons).

## Architecture

```
Open-Meteo API
      |
      v
extraction/fetch_weather.py ──> raw.weather_daily            (Postgres table)
                                       |
                                       v
                          dbt: staging.stg_weather           (view)
                                       |
                                       v
                          dbt: marts.fct_daily_weather       (table)
                                       |
                                       v
forecast/forecast_weather.py ──> marts.weather_forecast      (Postgres table)
                                       |
                                       v
                               Metabase dashboard

Airflow DAG "weather_pipeline" (@daily):
    extract_weather  >>  dbt_run  >>  forecast_weather
```

## Tech stack

| Layer          | Tool                                   | Where                        |
|----------------|----------------------------------------|------------------------------|
| Source         | Open-Meteo archive API                 | external, free, no key       |
| Extraction     | Python (`requests`, `psycopg2`)        | `extraction/`                |
| Warehouse      | Postgres 16 (Homebrew)                 | `sql/`                       |
| Transformation | dbt-core / dbt-postgres 1.8.x          | `dbt/weather_dbt/`           |
| Forecasting    | Python (`numpy`, `psycopg2`)           | `forecast/`                  |
| Orchestration  | Apache Airflow 2.9.3 (standalone mode) | `dags/`                      |
| Visualization  | Metabase (plain `.jar`)                | `metabase/` (not in git)     |

## Project structure

```
.
├── dags/
│   └── weather_pipeline_dag.py        # Airflow DAG: extract >> dbt run >> forecast
├── extraction/
│   ├── config.py                      # cities + how many days back to fetch
│   ├── fetch_weather.py               # Open-Meteo -> raw.weather_daily
│   └── requirements.txt
├── forecast/
│   ├── forecast_weather.py            # marts.fct_daily_weather -> marts.weather_forecast
│   └── requirements.txt
├── dbt/weather_dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml.example           # copy to profiles.yml (gitignored)
│   ├── macros/generate_schema_name.sql
│   └── models/
│       ├── staging/                   # stg_weather (view) + source + tests
│       └── marts/                     # fct_daily_weather (table)
├── sql/
│   └── init_warehouse_schemas.sql     # creates schemas + raw/forecast tables
├── .env.example                       # optional DB connection overrides
└── README.md
```

Not tracked by git: `.venv/`, `airflow_home/`, `metabase/`, and
`dbt/weather_dbt/profiles.yml`.

## How each step works

### 1. Extraction — `extraction/fetch_weather.py`

- Cities are configured in `extraction/config.py`: **Kigali, Nairobi,
  London, New York, Tokyo**.
- On every run it re-fetches the trailing **90 days** (`DAYS_BACK`) ending
  yesterday: max/min temperature, precipitation, and max wind speed.
- Rows are upserted into `raw.weather_daily` on `(city, date)`. Because it
  re-pulls a whole window, the job is idempotent and self-healing: a missed
  day gets filled in on the next run, with no state tracking needed.

### 2. Transformation — `dbt/weather_dbt`

- `staging.stg_weather` (view): a clean selection over the raw table, with
  `not_null` tests on `city` and `date`.
- `marts.fct_daily_weather` (table): one row per city per day, plus derived
  columns:
  - `temperature_range_c` = max − min temperature
  - `is_rain_day` = precipitation > 0
- A `generate_schema_name` macro override makes marts models land in the
  `marts` schema as-is (dbt's default would create `staging_marts`).

### 3. Forecasting — `forecast/forecast_weather.py`

- For each city, fits a straight-line trend (`numpy.polyfit`) over the last
  **30 days** of actuals in `marts.fct_daily_weather`.
- Projects max temperature and precipitation **7 days** past the latest
  actual (precipitation is clipped at 0), and upserts the predictions into
  `marts.weather_forecast`.
- Cities with fewer than 2 days of history are skipped.
- This is intentionally simple. It exists to give Metabase something to chart
  next to the actuals, not to be an accurate weather forecast.
- Each run overwrites predictions for future dates, so each date keeps the
  latest forecast made for it (the one made the day before its actuals
  arrived).

### 4. Orchestration — `dags/weather_pipeline_dag.py`

- DAG id `weather_pipeline`, scheduled `@daily`, `catchup=False`, 1 retry
  per task.
- `extract_weather` (PythonOperator) → `dbt_run` (BashOperator running the
  venv's `dbt run`) → `forecast_weather` (PythonOperator).

## Warehouse data model

| Table                        | Built by                        | Grain             | Key columns                                                                 |
|------------------------------|---------------------------------|-------------------|-----------------------------------------------------------------------------|
| `raw.weather_daily`          | `extraction/fetch_weather.py`   | city × day        | temps (max/min), `precipitation_mm`, `windspeed_max_kmh`, `loaded_at`        |
| `staging.stg_weather`        | dbt (view)                      | city × day        | same as raw                                                                 |
| `marts.fct_daily_weather`    | dbt (table)                     | city × day        | + `temperature_range_c`, `is_rain_day`                                      |
| `marts.weather_forecast`     | `forecast/forecast_weather.py`  | city × future day | `predicted_temp_max_c`, `predicted_precip_mm`, `generated_at`               |

## One-time setup (already done on this machine)

These steps were run once to provision the machine. They're kept here for
reference, or for setting this up on another Mac:

```bash
brew install postgresql@16 python@3.12 openjdk
brew services start postgresql@16

# Create the warehouse role + database, then schemas and tables
psql -U "$(whoami)" -d postgres -c "CREATE ROLE warehouse LOGIN PASSWORD 'warehouse';"
psql -U "$(whoami)" -d postgres -c "CREATE DATABASE warehouse OWNER warehouse;"
psql "postgresql://warehouse:warehouse@localhost:5432/warehouse" -f sql/init_warehouse_schemas.sql

# Project virtualenv with Airflow + dbt + extraction/forecast deps
python3.12 -m venv .venv
AIRFLOW_VERSION=2.9.3
PYTHON_VERSION=3.12
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
.venv/bin/pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}" \
    "dbt-core==1.8.*" "dbt-postgres==1.8.*" "requests==2.32.3" "psycopg2-binary==2.9.9"
.venv/bin/pip install -r forecast/requirements.txt   # numpy for the forecast step

# dbt profile (local only, not committed)
cp dbt/weather_dbt/profiles.yml.example dbt/weather_dbt/profiles.yml

# Airflow metadata db, pointed at this project's dags/ folder
export AIRFLOW_HOME="$(pwd)/airflow_home"
.venv/bin/airflow db migrate
# then edit airflow_home/airflow.cfg: dags_folder -> this project's dags/ folder,
# load_examples -> False (already done on this machine)

# macOS fork-safety fix (see "Known issues" below) - required for
# `airflow standalone` / gunicorn to not crash. Not tracked by git since
# .venv/ is gitignored - recreate these two files if the venv is rebuilt.
cat > .venv/lib/python3.12/site-packages/_patch_setproctitle_hook.py <<'EOF'
import sys

if sys.platform == "darwin":
    try:
        import setproctitle
    except ImportError:
        pass
    else:
        def _noop_title(title: str) -> None:
            return None

        setproctitle.setproctitle = _noop_title
        setproctitle.setthreadtitle = _noop_title
EOF
echo "import _patch_setproctitle_hook" > .venv/lib/python3.12/site-packages/_patch_setproctitle.pth

# Metabase jar (~660MB download from downloads.metabase.com)
mkdir -p metabase
curl -L -o metabase/metabase.jar "https://downloads.metabase.com/latest/metabase.jar"
```

> **dbt versions:** newer `dbt-core` releases (2.x) moved Postgres to an
> experimental adapter tier. This project pins `dbt-core`/`dbt-postgres` to
> the `1.8.x` line, which fully supports Postgres.

> **Upgrading an existing warehouse:** if your database was created before
> the forecast step existed, re-run the init script to add
> `marts.weather_forecast`. Every statement uses `IF NOT EXISTS`, so it's
> safe to re-run:
> ```bash
> psql "postgresql://warehouse:warehouse@localhost:5432/warehouse" -f sql/init_warehouse_schemas.sql
> ```

### Configuration

The Python scripts read their DB connection from `WAREHOUSE_DB_HOST`,
`WAREHOUSE_DB_PORT`, `WAREHOUSE_DB_NAME`, `WAREHOUSE_DB_USER`, and
`WAREHOUSE_DB_PASSWORD`. They fall back to the local defaults
(`localhost:5432`, database/user/password all `warehouse`), so `.env.example`
is only needed if you want to override them.

## Everyday use.

### 1. Make sure Postgres is running.

```bash
brew services list   # should show postgresql@16 as "started"
```

### 2. Run Airflow (webserver + scheduler in one process).

```bash
cd "/Users/janvier/Data Engineer Project"
source .venv/bin/activate
export AIRFLOW_HOME="$(pwd)/airflow_home"
airflow standalone
```

Activate the venv instead of calling `.venv/bin/airflow` directly.
`standalone` starts `airflow webserver`/`scheduler`/`triggerer` as
subprocesses that look for `airflow` on `PATH`, and that only works once the
venv is activated.

Open [localhost:8080](http://localhost:8080) and log in with
`admin` / `admin123`. Unpause `weather_pipeline` and trigger it manually to
run it now (it's also scheduled `@daily`). Leave Airflow running in its own
terminal tab.

> `standalone` auto-generates a random admin password the *first* time it
> creates that user, and prints it only once. If you get "Invalid login",
> reset it:
> `airflow users reset-password --username admin --password admin123`

### 3. Run Metabase

```bash
cd "/Users/janvier/Data Engineer Project/metabase"
/opt/homebrew/opt/openjdk/bin/java -jar metabase.jar
```

The first run takes a minute or two to set up Metabase's internal database.
Open [localhost:3000](http://localhost:3000), finish the one-time setup, and
add a Postgres connection:

- Host: `localhost`, Port: `5432`, Database: `warehouse`
- User: `warehouse`, Password: `warehouse`

Dashboard ideas:

- Average max temperature by city over time (`marts.fct_daily_weather`)
- Rainy days per city per month (`is_rain_day`)
- Actuals vs. forecast: join `marts.fct_daily_weather` and
  `marts.weather_forecast` on `(city, date)` and plot both lines

## Running steps manually (outside Airflow)

Handy while developing, so you don't have to re-trigger the whole DAG.

```bash
# Extraction
cd extraction
../.venv/bin/python fetch_weather.py

# dbt models + tests
cd ../dbt/weather_dbt
../../.venv/bin/dbt run --profiles-dir .
../../.venv/bin/dbt test --profiles-dir .

# Forecast (needs marts.fct_daily_weather to be populated first)
cd ../../forecast
../.venv/bin/python forecast_weather.py
```

## Known issues (macOS)

### Airflow/gunicorn crash-loops with SIGSEGV

`airflow standalone` (and plain `airflow webserver`) forks worker processes,
and each forked worker calls `setproctitle()` to rename itself for `ps`/
Activity Monitor. On this macOS version, that native call segfaults inside
CoreFoundation/os_log right after fork, even with `setproctitle`'s own
built-in fix for this class of bug (its issue #113). Left unfixed, gunicorn
keeps restarting the crashing worker in an endless loop, which drives up CPU
use and the number of processes.

**Fix (already applied to this project's `.venv`):** a `.pth` file in the
venv's `site-packages` that turns `setproctitle` into a harmless no-op on
macOS for every Python process using this venv. It only changes how
processes are labeled in `ps`; Airflow itself is unaffected.

If `airflow standalone` crash-loops with repeated `SIGSEGV` lines again (for
example after recreating the venv), recreate the two files from the setup
script above. Or check whether a newer `setproctitle` release has fixed it
upstream (`pip index versions setproctitle`) and remove the workaround if so.

### Task processes hang forever on the macOS proxy lookup

Before every HTTP call, `requests` checks the OS for a configured proxy. On
macOS this goes through `_scproxy`, which talks to the `cfprefsd` system
service. When that happens inside a subprocess Airflow started (as
`extract_weather` always is), the call can hang forever instead of failing.
The process sits at ~100% CPU, and Airflow never retries or kills it. Stuck
processes pile up across runs and starve the scheduler of CPU. That's what
caused the "scheduler does not appear to be running" banner (not SQLite).

**Fix (already applied in `fetch_weather.py`):** HTTP calls go through a
`requests.Session()` with `trust_env = False`, which skips the proxy lookup
entirely. There's no proxy to honor in this project anyway.

If you see an `airflow tasks run ... extract_weather` process stuck at ~100%
CPU for more than a few seconds (`ps aux | grep extract_weather`), `kill -9`
the stuck PID(s). Send any new HTTP calls you add to the project through a
session set up the same way.

### Postgres connections can also hang forever (same root cause, different call)

The exact same `cfprefsd` flakiness above can also strike `psycopg2.connect()`:
`libpq` probes for a GSSAPI/Kerberos credential cache before every connection
(even though this project never uses Kerberos), and that probe routes
through the same unreliable macOS service and can hang forever.

**Partial fix:** every `psycopg2.connect()` call passes `gssencmode="disable"`
to skip that probe. This helps but isn't 100% reliable on its own - the hang
is intermittent, not deterministic.

**The real fix:** a `signal.alarm()`-based timeout does **not** work here.
The hang happens inside a macOS Mach IPC call that doesn't yield back to
Python between instructions, so the alarm never fires - confirmed by testing
it directly. The only thing that reliably stops a hung connection is
`SIGKILL` sent from *outside* the process. So `extraction/fetch_weather.py`
and `forecast/forecast_weather.py` both run their real work in a
`multiprocessing.Process` with a wall-clock budget (`RUN_TIMEOUT_SECONDS`,
120s); if it doesn't finish in time, the parent kills the subprocess outright
and raises, so Airflow fails the task and retries instead of blocking the
pipeline for hours. `dbt_run` doesn't need this treatment - it's a
`BashOperator`, so Airflow's own `execution_timeout` (5 minutes, set in
`default_args`) is monitored from a *different* process than the one that
could hang, which stays responsive to normal signals.

If a scheduled run ever sits in "running" for hours with no data showing up,
check `ps aux | grep "tasks run"` for a stuck process before assuming
anything else is wrong - this class of bug has now shown up in three
unrelated call sites (`requests`, `libpq`, likely not the last).

## Stopping / resetting

```bash
# Stop Airflow:  Ctrl+C in its terminal
# Stop Metabase: Ctrl+C in its terminal
brew services stop postgresql@16   # stop Postgres (data persists)
```

To fully reset the warehouse data:

```bash
psql -U "$(whoami)" -d postgres -c "DROP DATABASE warehouse;"
psql -U "$(whoami)" -d postgres -c "CREATE DATABASE warehouse OWNER warehouse;"
psql "postgresql://warehouse:warehouse@localhost:5432/warehouse" -f sql/init_warehouse_schemas.sql
```

## Next steps / ideas

- Add dbt tests for the marts layer (`unique` on `(city, date)`,
  `accepted_values`, singular tests for physically impossible values).
- Keep the full forecast history (e.g. add a `generated_date` column to the
  forecast table's key) so predictions made N days ahead can be scored
  against actuals.
- Replace the linear trend with a seasonal model, and handle missing values
  before fitting.
- Add air-quality data (Open-Meteo has a free air-quality API) as a second
  source.
- Add retry/backoff in the DAG to handle API outages gracefully.
- Swap Metabase for Superset, or build a Streamlit app for a custom
  dashboard.
- Move the warehouse to a free-tier cloud Postgres (e.g. Supabase, Neon) and
  Airflow to a small VM once you're ready to go beyond local.
