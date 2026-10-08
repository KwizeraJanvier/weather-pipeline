# Weather Batch Pipeline

A beginner-friendly, fully local data engineering project. Every day it:

1. **Extracts** daily historical weather for five cities from the free
   [Open-Meteo](https://open-meteo.com/) API (no API key needed),
2. **Loads** it into a Postgres warehouse,
3. **Transforms** it into an analytics-ready table with dbt,
4. **Forecasts** the next 7 days per city with a simple trend model,
5. **Orchestrates** all of the above with Airflow, and
6. **Visualizes** actuals and forecasts in Metabase - and, as a full-stack
   companion, a small custom **FastAPI + vanilla-JS web app**
   (`api/` + `frontend/`) that reads from the same warehouse.

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
                       ┌───────────────┴───────────────┐
                       v                                v
               Metabase dashboard          api/main.py (FastAPI) ──> frontend/
                                            GET /api/cities, /api/weather/{city},
                                            /api/forecast/{city}, /api/rain-stats

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
| Web app API    | FastAPI + `psycopg2`                   | `api/`                       |
| Web app UI     | Plain HTML/CSS/JS + Chart.js (CDN)     | `frontend/`                  |

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
│   ├── init_warehouse_schemas.sql     # creates schemas + raw/forecast tables
│   └── init_app_schema.sql            # app.users/audit_log + app_readonly role
├── api/
│   ├── main.py                        # FastAPI app: /api/* + serves frontend/
│   ├── auth.py                        # bcrypt hashing, sessions, role checks
│   ├── audit.py                       # writes/reads app.audit_log
│   ├── db.py                          # psycopg2 connection helpers
│   ├── sql_runner.py                  # validates + runs admin SQL queries
│   ├── pipeline.py                    # reads Airflow's own SQLite metadata
│   ├── metabase_embed.py              # signs Metabase static-embed JWTs
│   └── requirements.txt
├── frontend/
│   ├── login.html / login.js          # signup + login form, show/hide password
│   ├── index.html                     # app shell: Dashboard/Metabase/Database/
│   │                                   #   Pipeline/Audit Log
│   ├── app.js                         # calls /api/*, renders with Chart.js
│   └── style.css
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

### 5. Web app — `api/main.py` + `frontend/`

- A FastAPI app, gated behind a login (`app.users`, bcrypt-hashed passwords,
  signed-cookie sessions), with JSON endpoints under `/api/*` for the
  dashboard (cities, actuals, forecast, rain stats - any logged-in user, and
  auto-refreshed every 60s - see "Why not real-time streaming" below), an
  embedded Metabase dashboard (any logged-in user, via a signed JWT so it
  stays behind this app's login rather than a public link), the database
  tool (admin only - see "Security model" below), pipeline status (any
  logged-in user, reads Airflow's own SQLite file directly), and the audit
  log (admin only).
- `StaticFiles` mounted at `/` serves `frontend/`'s plain HTML/CSS/JS
  directly from the same process, so the API and UI are one app, one port,
  no CORS configuration needed.
- The frontend has no build step - it's loaded as-is by the browser, with
  Chart.js pulled from a CDN `<script>` tag. `login.html`/`login.js` handle
  signup/login (with a show/hide toggle on the password field); `index.html`/
  `app.js` are the post-login app shell with its five sidebar sections.
- This is a separate, independent consumer of the warehouse - it doesn't
  participate in the DAG and has no effect on Metabase or vice versa.

#### Why not real-time streaming

The pipeline updates `marts.*` once a day. A dashboard that polls every 60
seconds (what this does) shows new data within a minute of it landing -
indistinguishable in practice from true streaming, for data that only
changes once every 24 hours. WebSockets/server-sent events would add real
complexity (a persistent connection, reconnect handling, a reason for the
backend to push instead of the client asking) to solve a latency problem
that doesn't exist here. Same reasoning as the Kafka question elsewhere in
this project - match the tool to the actual shape of the data.

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

# App auth schema + the read-only role the web app's SQL tool runs as.
# Needs CREATE ROLE, so run as the superuser ($(whoami)), not `warehouse`.
psql -U "$(whoami)" -d warehouse -f sql/init_app_schema.sql

# Project virtualenv with Airflow + dbt + extraction/forecast deps
python3.12 -m venv .venv
AIRFLOW_VERSION=2.9.3
PYTHON_VERSION=3.12
CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"
.venv/bin/pip install "apache-airflow==${AIRFLOW_VERSION}" --constraint "${CONSTRAINT_URL}" \
    "dbt-core==1.8.*" "dbt-postgres==1.8.*" "requests==2.32.3" "psycopg2-binary==2.9.9"
.venv/bin/pip install -r forecast/requirements.txt   # numpy for the forecast step
.venv/bin/pip install -r api/requirements.txt        # fastapi, bcrypt, etc. for the web app

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

### 2. Airflow runs as a background service - you shouldn't need to start it

Airflow (`webserver` + `scheduler` + `triggerer`, via `standalone`) runs as a
macOS `launchd` service, `com.weatherpipeline.airflow`, so the daily schedule
keeps firing without a terminal window open. It starts automatically at
login and restarts itself if it crashes.

```bash
launchctl list | grep weatherpipeline   # confirm it's running
```

Open [localhost:8080](http://localhost:8080) and log in with
`admin` / `admin123`. Unpause `weather_pipeline` if needed.

> `standalone` auto-generates a random admin password the *first* time it
> creates that user, and prints it only once. If you get "Invalid login",
> reset it:
> `airflow users reset-password --username admin --password admin123`

**Do not run `airflow standalone` manually in a terminal** - that creates a
second instance fighting the service for the same database and port 8080,
which is what caused repeated "scheduler not running" / stale data problems
before this was turned into a proper service. If you ever need to restart it
intentionally:

```bash
launchctl kickstart -k gui/$(id -u)/com.weatherpipeline.airflow
```

To stop it (note: plain `stop` just gets restarted by `KeepAlive` - use
`bootout` to actually turn it off, `bootstrap` to turn it back on):

```bash
launchctl bootout gui/$(id -u)/com.weatherpipeline.airflow
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.weatherpipeline.airflow.plist
```

The service definition lives at
`~/Library/LaunchAgents/com.weatherpipeline.airflow.plist`; its logs are in
`airflow_home/service_logs/`.

If the webserver ever seems unreachable while `launchctl list` shows the
service running: check for a stale `airflow_home/airflow-webserver.pid` left
over from a force-killed previous instance (same root cause as the Postgres
`postmaster.pid` issue above) - delete it and `kickstart -k` again.

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

### 4. Run the web app (FastAPI + frontend)

```bash
cd "/Users/janvier/Data Engineer Project/api"
export WAREHOUSE_DB_HOST=localhost WAREHOUSE_DB_PORT=5432 WAREHOUSE_DB_NAME=warehouse \
       WAREHOUSE_DB_USER=warehouse WAREHOUSE_DB_PASSWORD=warehouse
export APP_READONLY_DB_USER=app_readonly APP_READONLY_DB_PASSWORD=app_readonly
../.venv/bin/uvicorn main:app --port 8001
```

Open [localhost:8001](http://localhost:8001) - it redirects to a login page
since every page and API route requires an account. **The first person to
sign up becomes an admin automatically**; everyone after that is a "viewer."
There's no UI to promote a user later - do it by hand if needed:
```sql
UPDATE app.users SET role = 'admin' WHERE email = '...';
```

Once logged in, the sidebar has five sections:

- **Dashboard** (any logged-in user) - the actual-vs-forecast chart and
  rain-analysis table, auto-refreshing every 60s (pauses while the browser
  tab isn't visible). Pick a city from the dropdown.
- **Metabase** (any logged-in user) - the Metabase dashboard, embedded via
  a signed JWT (not a public link - see "Embedding Metabase" below for the
  one-time setup this needs). Shows a plain error message until configured.
- **Database** (admin only) - a text box to run read-only SQL directly
  against the warehouse. See "Security model" below for how this is kept
  safe even though it accepts arbitrary queries.
- **Data Pipeline** (any logged-in user) - recent Airflow DAG runs and, for
  whichever run you click, its three tasks and their states. Read-only -
  reads Airflow's own SQLite metadata DB directly, no Airflow API needed.
- **Audit Log** (admin only) - every signup, login (success and failure),
  logout, and SQL query run through the Database tool (including ones the
  SELECT-only check blocked), newest first.

FastAPI serves both the JSON API (under `/api/*`) and the static frontend
from the same process, so there's nothing else to run and no CORS setup
needed.

#### Embedding Metabase

This needs a couple of one-time clicks in Metabase itself (can't be done
with page automation - it needs your Metabase login):

1. In Metabase: **Admin settings → Embedding** → enable embedding → copy
   the **embedding secret key**.
2. Open the dashboard you want embedded, open its URL - the number at the
   end is its **dashboard ID** (e.g. `localhost:3000/dashboard/2` → `2`).
3. On that dashboard, **Share → Embed this dashboard → Publish**.
4. Set both before starting the web app:
   ```bash
   export METABASE_EMBED_SECRET=<the secret key from step 1>
   export METABASE_DASHBOARD_ID=<the id from step 2>
   ```

Until these are set, the Metabase section just shows a message saying so -
nothing breaks. This is deliberately **static (signed) embedding, not a
public link**: the JWT is only ever generated for a request that already
passed this app's own login, so the Metabase dashboard stays behind the
same auth as everything else here, instead of being reachable by anyone who
has the URL.

#### Security model

- **Passwords** are hashed with `bcrypt`, never stored or logged in plain
  text, and the login/signup form has a show/hide toggle so you can check
  what you typed without weakening how it's stored. Sessions are signed
  cookies (`SessionMiddleware`), not JWTs or anything stored client-side
  beyond the cookie itself.
- **The SQL query tool never uses the app's own database credentials.** It
  connects as `app_readonly`, a Postgres role created in
  `sql/init_app_schema.sql` with `SELECT`-only grants on `raw`/`staging`/
  `marts` and explicitly **no** access to the `app` schema (where password
  hashes live) - so even a bug in the app's own query validation can't turn
  into a write, and can never leak another user's credentials. This is
  checked twice: once at the database level (real enforcement) and once in
  `api/sql_runner.py` (keyword/shape check, for a clearer error message).
  `app_readonly` also has a 5-second `statement_timeout` set, so a runaway
  query can't hang the connection.
- **Role checks** happen server-side on every request (`require_admin` in
  `api/auth.py`), not just by hiding the nav link in the frontend - a viewer
  calling `/api/db/query` directly gets a 403 regardless of what the UI
  shows them.
- **Every security-relevant action is written to `app.audit_log`** (see
  `api/audit.py`) - signups, logins (success and failure), logouts, and
  every SQL query run through the Database tool, including ones that got
  blocked. Visible on the Audit Log page (admin only).

API endpoints, if you want to poke at them directly or build more frontend
on top (all except `/api/auth/*` and `/api/health` require a logged-in
session; `/api/db/*` and `/api/audit/*` additionally require the admin role):

| Endpoint                              | Returns                                              |
|----------------------------------------|-------------------------------------------------------|
| `POST /api/auth/signup`               | create an account, log in, `{email, role}`           |
| `POST /api/auth/login`                | log in, `{email, role}`                              |
| `POST /api/auth/logout`               | clear the session                                     |
| `GET /api/auth/me`                    | the logged-in user, or 401                           |
| `GET /api/cities`                      | list of tracked city names                           |
| `GET /api/weather/{city}`              | last `days` (default 30) of actuals for a city       |
| `GET /api/forecast/{city}`             | current forward-looking forecast (not past ones)     |
| `GET /api/rain-stats`                  | rain-day % and avg temp (rain vs. no-rain) per city  |
| `GET /api/metabase/embed-url`          | a signed, short-lived embed URL for the dashboard    |
| `GET /api/db/tables`                   | schema.table names in raw/staging/marts (admin)      |
| `POST /api/db/query`                   | run a read-only SQL query (admin)                    |
| `GET /api/pipeline/runs`               | last 10 DAG runs                                     |
| `GET /api/pipeline/runs/{id}/tasks`    | task states for one run                              |
| `GET /api/audit/log`                   | last 100 audit log entries (admin)                   |
| `GET /api/health`                      | `{"status": "ok"}` if the DB connection works        |

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
