# Weather Batch Pipeline

A beginner-friendly data engineering project. Every day it:

1. **Extracts** daily historical weather for five cities from the free
   [Open-Meteo](https://open-meteo.com/) API (no API key needed),
2. **Loads** it into a Postgres warehouse,
3. **Transforms** it into an analytics-ready table with dbt,
4. **Forecasts** the next 7 days per city with a simple trend model,
5. **Orchestrates** all of the above, and
6. **Visualizes** actuals and forecasts in Metabase - and, as a full-stack
   companion, a custom **FastAPI + vanilla-JS web app** (`api/` +
   `frontend/`) with logins, a SQL tool, pipeline status and an audit log.

## Two ways to run it

The same code runs in two environments. They are independent copies - each
has its own database, its own users, and its own data.

| | **Cloud** (the "real" deployment) | **Local** (Docker) |
|---|---|---|
| Database | [Neon](https://neon.tech) (free cloud Postgres) | Postgres container |
| Pipeline runs on | GitHub Actions, daily at 06:00 UTC | Airflow container, `@daily` |
| Web app | Render web service (public URL) | `webapp` container, `localhost:8001` |
| Metabase / Power BI | point at Neon | Metabase container, `localhost:3000` |
| Needs your Mac on? | No | Yes |

**Why the cloud pipeline uses GitHub Actions and not Airflow:** the author's
network blocks outbound Postgres connections (port 5432) entirely, so
anything running on their Mac - including a local Airflow - can't write to
a cloud database. GitHub's runners have normal networking. (For the same
reason, schema changes to Neon also go through a GitHub Actions workflow
rather than `psql` from a laptop.) The local Docker stack is for developing
and testing without touching the cloud.

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

The pipeline, three steps: extract_weather  >>  dbt_run  >>  forecast_weather
    cloud: .github/workflows/daily_pipeline.yml (GitHub Actions)
    local: dags/weather_pipeline_dag.py        (Airflow DAG, @daily)
```

## Tech stack

| Layer          | Tool                                         | Where                          |
|----------------|----------------------------------------------|--------------------------------|
| Source         | Open-Meteo archive API                       | external, free, no key         |
| Extraction     | Python (`requests`, `psycopg2`)              | `extraction/`                  |
| Warehouse      | Postgres 16 (Docker) / Neon (cloud)          | `sql/`                         |
| Transformation | dbt-core / dbt-postgres 1.8.x                | `dbt/weather_dbt/`             |
| Forecasting    | Python (`numpy`, `psycopg2`)                 | `forecast/`                    |
| Orchestration  | Airflow 2.9.3 (Docker) / GitHub Actions (cloud) | `dags/`, `.github/workflows/` |
| Visualization  | Metabase; Power BI                           | `docker-compose.yml`           |
| Web app API    | FastAPI + `psycopg2`                         | `api/`                         |
| Web app UI     | Plain HTML/CSS/JS + Chart.js (CDN)           | `frontend/`                    |
| Hosting        | Render (web app), Neon (database)            | see "Cloud"                    |

## Project structure

```
.
├── .github/workflows/
│   ├── setup_neon.yml                 # manual, one-time: apply schema + roles to Neon
│   └── daily_pipeline.yml             # cloud pipeline: extract >> dbt run >> forecast
├── dags/
│   └── weather_pipeline_dag.py        # local Airflow DAG: same three steps
├── extraction/                        # Open-Meteo -> raw.weather_daily
├── forecast/                          # marts.fct_daily_weather -> marts.weather_forecast
├── dbt/weather_dbt/                   # staging + marts models
├── sql/
│   ├── init_warehouse_schemas.sql     # raw/staging/marts schemas + raw/forecast tables
│   ├── init_app_schema.sql            # app.users/audit_log + app_readonly role (Docker)
│   ├── init_app_schema_neon.sql       # same, for Neon (password comes from a secret)
│   └── create_airflow_db.sql          # Docker only: Airflow's metadata database
├── api/                               # FastAPI app (auth, SQL tool, pipeline status, ...)
├── frontend/                          # login page + app shell (no build step)
├── docker/                            # Dockerfiles for Airflow(+dbt) and the web app
├── docker-compose.yml                 # the whole local stack
├── .env.example                       # settings for docker-compose
└── README.md
```

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

### 4. Orchestration

The same three steps run in both environments:

- **Local (Docker):** `dags/weather_pipeline_dag.py` - DAG id
  `weather_pipeline`, `@daily`, `catchup=False`, 1 retry and a 5-minute
  timeout per task. `extract_weather` (PythonOperator) → `dbt_run`
  (BashOperator running `dbt run`) → `forecast_weather` (PythonOperator).
- **Cloud:** `.github/workflows/daily_pipeline.yml` - a scheduled GitHub
  Actions workflow (06:00 UTC, also triggerable by hand) that installs the
  dependencies and runs `fetch_weather.py`, `dbt run`, `forecast_weather.py`
  in order against Neon.

### 5. Web app — `api/main.py` + `frontend/`

- A FastAPI app, gated behind a login (`app.users`, bcrypt-hashed passwords,
  signed-cookie sessions), with JSON endpoints under `/api/*` for the
  dashboard (cities, actuals, forecast, rain stats - any logged-in user, and
  auto-refreshed every 60s - see "Why not real-time streaming" below), an
  embedded Metabase dashboard (any logged-in user, via a signed JWT so it
  stays behind this app's login rather than a public link), the database
  tool (admin only - see "Security model" below), pipeline status (any
  logged-in user), and the audit log (admin only).
- Pipeline status reads from wherever the pipeline actually runs, chosen by
  the `PIPELINE_SOURCE` environment variable: `github` (default - GitHub's
  Actions API, each workflow step shown as a "task") or `airflow` (set in
  `docker-compose.yml` - Airflow's `airflow_meta` database). Same response
  shape either way, so the frontend doesn't care.
- `StaticFiles` mounted at `/` serves `frontend/`'s plain HTML/CSS/JS
  directly from the same process, so the API and UI are one app, one port,
  no CORS configuration needed.
- The frontend has no build step - it's loaded as-is by the browser, with
  Chart.js pulled from a CDN `<script>` tag. `login.html`/`login.js` handle
  signup/login (with a show/hide toggle on the password field); `index.html`/
  `app.js` are the post-login app shell with its five sidebar sections.
- This is a separate, independent consumer of the warehouse - it doesn't
  participate in the pipeline and has no effect on Metabase or vice versa.

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

## Cloud (Neon + GitHub Actions + Render)

### How it fits together

- **Neon** holds the warehouse (`raw`/`staging`/`marts`) *and* the web app's
  own tables (`app.users`, `app.audit_log`), in one database.
- **GitHub Actions** runs the daily pipeline against Neon, and also applies
  schema changes (see below).
- **Render** hosts the web app, reading from Neon.
- The repository is public, so **no credentials are ever committed** - they
  live in GitHub Actions secrets and in Render's environment variables.

### GitHub Actions secrets

Set once with `gh secret set <NAME>` (or the repo's Settings → Secrets):

| Secret | Value |
|---|---|
| `NEON_HOST` | Neon's **direct** hostname (the connection string's host *without* `-pooler`) |
| `NEON_USER` | the Neon role, e.g. `neondb_owner` |
| `NEON_PASSWORD` | that role's password |
| `NEON_DBNAME` | the database name, e.g. `neondb` |
| `APP_READONLY_DB_PASSWORD` | a new random password for the web app's read-only SQL role |

### One-time setup of a fresh Neon database

Run the **One-time Neon setup** workflow (Actions tab → *Run workflow*, or
`gh workflow run setup_neon.yml`). It applies `sql/init_warehouse_schemas.sql`
and `sql/init_app_schema_neon.sql`, creating the schemas, tables and the
`app_readonly` role. It's safe to re-run: re-running it also updates the
`app_readonly` password to match the secret, which is how you rotate it.

Then run the **Daily weather pipeline** workflow once by hand
(`gh workflow run daily_pipeline.yml`) to backfill 90 days of data; after
that it runs by itself every day.

> You can't just `psql` into Neon from this author's Mac (outbound port 5432
> is blocked on their network) - that's the reason schema changes go through
> a workflow. Anywhere with normal networking can connect directly.

### Deploying the web app on Render

1. Render → **New → Web Service**, connect the GitHub repo
   (`KwizeraJanvier/weather-pipeline`).
2. Settings:
   - **Root Directory:** `api`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
3. Environment variables:

   ```
   PYTHON_VERSION=3.12.7
   WAREHOUSE_DB_HOST=<Neon direct host>
   WAREHOUSE_DB_PORT=5432
   WAREHOUSE_DB_NAME=neondb
   WAREHOUSE_DB_USER=neondb_owner
   WAREHOUSE_DB_PASSWORD=<Neon password>
   WAREHOUSE_DB_SSLMODE=require
   APP_READONLY_DB_USER=app_readonly
   APP_READONLY_DB_PASSWORD=<same value as the APP_READONLY_DB_PASSWORD secret>
   SESSION_SECRET_KEY=<a long random string: openssl rand -hex 32>
   ```

   `PYTHON_VERSION` pins the Python that's actually been tested. Render's
   default can be much newer, and an old `psycopg2-binary` (2.9.9) crashed at
   startup on 3.14 with `undefined symbol: _PyInterpreterState_Get` - that's
   why `api/requirements.txt` now pins `psycopg2-binary==2.9.11`, the first
   release with 3.14 wheels.
4. Redeploy after pushing changes (a service connected via "Public Git
   Repository" doesn't auto-deploy; connecting your GitHub account does).

Leave the `METABASE_*` variables unset unless Metabase is hosted somewhere
the deployed app can reach - until then the Metabase section just says
embedding isn't configured. Render's free tier spins down when idle, so the
first request after a quiet spell takes ~50 seconds.

### Power BI

Power BI Desktop is Windows-only. Point it at Neon (Get Data → PostgreSQL;
server = the direct host, database `neondb`, SSL on) and read from
`marts.fct_daily_weather` / `marts.weather_forecast`. For automatic updates,
publish to the Power BI Service and add a scheduled refresh (Neon is
cloud-reachable, so no gateway is needed) an hour or so after the 06:00 UTC
pipeline run. Desktop itself only refreshes when you press Refresh.

## Local (Docker)

A full copy of the stack on your own machine: Postgres, Airflow (with dbt),
Metabase and the web app. It doesn't touch the cloud setup.

### Start it

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
   and **open it once** - the first launch asks for your password and a
   license agreement, and `docker` isn't available until it's running.
2. Free the ports it needs - **5432** (Postgres), **8080** (Airflow),
   **3000** (Metabase), **8001** (web app) - e.g. stop any native Postgres.
3. From the project folder:

   ```bash
   cp .env.example .env          # defaults work as-is
   docker compose build
   docker compose up airflow-init
   docker compose up -d
   ```

| Service | URL | Login |
|---|---|---|
| Web app | [localhost:8001](http://localhost:8001) | sign up - the first account becomes admin |
| Airflow | [localhost:8080](http://localhost:8080) | `admin` / `admin` |
| Metabase | [localhost:3000](http://localhost:3000) | create one on first run |
| Postgres | `localhost:5432` | `warehouse` / `warehouse`, database `warehouse` |

The local database starts **empty**. In Airflow, unpause `weather_pipeline`
and trigger it once; it backfills 90 days, then runs daily while the stack
is up. (The schemas, the `app_readonly` role and Airflow's metadata database
are created automatically the first time the Postgres container starts.)

In Metabase, add a PostgreSQL database with host `postgres` (the container's
name - not `localhost`), port `5432`, database `warehouse`, user and password
`warehouse`.

### Everyday commands

```bash
docker compose ps                    # what's running
docker compose logs -f webapp        # follow one service's logs
docker compose up -d --build webapp  # rebuild + restart after changing api/ or frontend/
docker compose down                  # stop everything (data is kept)
docker compose down -v               # stop and DELETE all local data (fresh start)
```

Run a single pipeline step by hand inside the Airflow container:

```bash
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/extraction && python fetch_weather.py"
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/dbt/weather_dbt && dbt run --profiles-dir ."
docker compose exec airflow-scheduler bash -c "cd /opt/airflow/forecast && python forecast_weather.py"
```

(`dbt` needs `dbt/weather_dbt/profiles.yml` - copy `profiles.yml.example` to
`profiles.yml` once; it's gitignored and reads the same `WAREHOUSE_DB_*`
variables the containers already set.)

## Using the web app

Open the deployed URL (cloud) or [localhost:8001](http://localhost:8001)
(Docker). It redirects to a login page, since every page and API route
requires an account. **The first person to sign up becomes an admin
automatically**; everyone after that is a "viewer." Users are stored in the
environment's own database, so the cloud app and the local app have separate
accounts. There's no UI to promote a user later - do it by hand if needed:

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
- **Data Pipeline** (any logged-in user) - recent pipeline runs and, for
  whichever run you click, its steps and their states. Read-only.
- **Audit Log** (admin only) - every signup, login (success and failure),
  logout, and SQL query run through the Database tool (including ones the
  SELECT-only check blocked), newest first.

### Running the web app without Docker

```bash
cd api
pip install -r requirements.txt
export WAREHOUSE_DB_HOST=... WAREHOUSE_DB_PORT=5432 WAREHOUSE_DB_NAME=... \
       WAREHOUSE_DB_USER=... WAREHOUSE_DB_PASSWORD=...
export APP_READONLY_DB_USER=app_readonly APP_READONLY_DB_PASSWORD=...
uvicorn main:app --port 8001
```

(Add `WAREHOUSE_DB_SSLMODE=require` when pointing at a hosted database.)
Other settings, all optional: `SESSION_SECRET_KEY`, `PIPELINE_SOURCE`
(`github` or `airflow`), `METABASE_SITE_URL` / `METABASE_EMBED_SECRET` /
`METABASE_DASHBOARD_ID`, `GITHUB_TOKEN` (raises GitHub's API rate limit for
the pipeline page).

### Embedding Metabase

This needs a couple of one-time clicks in Metabase itself (can't be done
with page automation - it needs your Metabase login):

1. In Metabase: **Admin settings → Embedding** → enable embedding → copy
   the **embedding secret key**.
2. Open the dashboard you want embedded, open its URL - the number at the
   end is its **dashboard ID** (e.g. `localhost:3000/dashboard/2` → `2`).
3. On that dashboard, **Share → Embed this dashboard → Publish**.
4. Set both before starting the web app - for Docker, put them in `.env` and
   run `docker compose up -d webapp`; otherwise export them:
   ```bash
   export METABASE_EMBED_SECRET=<the secret key from step 1>
   export METABASE_DASHBOARD_ID=<the id from step 2>
   ```
   Keep the secret out of git - it can forge embed tokens for that Metabase.
   (The embedded dashboard also has to be reachable from the *viewer's*
   browser, so a deployed app can only embed a Metabase that's hosted
   somewhere public, not one on `localhost`.)

Until these are set, the Metabase section just shows a message saying so -
nothing breaks. This is deliberately **static (signed) embedding, not a
public link**: the JWT is only ever generated for a request that already
passed this app's own login, so the Metabase dashboard stays behind the
same auth as everything else here, instead of being reachable by anyone who
has the URL.

### Security model

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

## A note on macOS

`extraction/fetch_weather.py` and `forecast/forecast_weather.py` run their
real work in a subprocess with a 120-second wall-clock limit **on macOS
only** (elsewhere they just run inline). That's left over from running the
pipeline natively on a Mac, where certain system calls (`requests`' proxy
lookup, `libpq`'s Kerberos/GSS probe) could hang forever inside the
`cfprefsd` system service, in a way a Python-level timeout can't interrupt -
only killing the process from outside works. `requests` is also configured
with `trust_env = False` and the Postgres connections with
`gssencmode="disable"` to avoid those code paths. None of this matters in
Docker or on GitHub Actions; it's kept so running the scripts directly on a
Mac still works.

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
- Host Metabase too (e.g. on Render with its own app database) so the
  embedded dashboard works from the deployed web app.
- Switch the Render service to a linked GitHub account so it auto-deploys.
