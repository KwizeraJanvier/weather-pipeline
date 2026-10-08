import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

import pipeline
from audit import log_action, recent_entries
from auth import create_user, get_current_user, get_user_by_email, require_admin, verify_password
from db import query
from metabase_embed import get_embed_url
from sql_runner import run_query

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Weather Pipeline App")

# SESSION_SECRET_KEY should be a real random value if this is ever reachable
# beyond your own machine. The fallback below is fine for local-only use
# (same tier as the other local-dev-only defaults documented in the README)
# but sessions signed with it are not secure against someone who reads this
# source file, same tradeoff as any other hardcoded local-dev secret here.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET_KEY", "local-dev-only-secret-change-if-ever-deployed"),
    session_cookie="weather_app_session",
    same_site="lax",
)


@app.exception_handler(HTTPException)
async def auth_aware_exception_handler(request: Request, exc: HTTPException):
    # Plain JSON errors - the frontend decides what to do (e.g. redirect to
    # /login.html on a 401) rather than the server trying to guess.
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


class SignupBody(BaseModel):
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class QueryBody(BaseModel):
    sql: str


# ---- Auth ----------------------------------------------------------------


@app.post("/api/auth/signup")
def signup(body: SignupBody, request: Request):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user = create_user(body.email, body.password)
    request.session["user_id"] = user["id"]
    log_action(user["email"], "signup", user_id=user["id"], detail=f"role={user['role']}")
    return {"email": user["email"], "role": user["role"]}


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request):
    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        log_action(body.email, "login_failed")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    request.session["user_id"] = user["id"]
    log_action(user["email"], "login_success", user_id=user["id"])
    return {"email": user["email"], "role": user["role"]}


@app.post("/api/auth/logout")
def logout(request: Request, user: dict = Depends(get_current_user)):
    log_action(user["email"], "logout", user_id=user["id"])
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return {"email": user["email"], "role": user["role"]}


# ---- Dashboard (logged-in users) ------------------------------------------


@app.get("/api/health")
def health():
    query("SELECT 1")
    return {"status": "ok"}


@app.get("/api/cities")
def list_cities(user: dict = Depends(get_current_user)):
    rows = query("SELECT DISTINCT city FROM marts.fct_daily_weather ORDER BY city")
    return [row["city"] for row in rows]


@app.get("/api/weather/{city}")
def city_weather(city: str, days: int = 30, user: dict = Depends(get_current_user)):
    rows = query(
        """
        SELECT date, temperature_max_c, temperature_min_c, precipitation_mm,
               windspeed_max_kmh, is_rain_day
        FROM marts.fct_daily_weather
        WHERE city = %s AND date >= current_date - %s::int
        ORDER BY date
        """,
        (city, days),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"No data for city '{city}'")
    return rows


@app.get("/api/forecast/{city}")
def city_forecast(city: str, user: dict = Depends(get_current_user)):
    return query(
        """
        SELECT date, predicted_temp_max_c, predicted_precip_mm
        FROM marts.weather_forecast
        WHERE city = %s AND date >= current_date
        ORDER BY date
        """,
        (city,),
    )


@app.get("/api/rain-stats")
def rain_stats(user: dict = Depends(get_current_user)):
    return query(
        """
        SELECT
            city,
            count(*) FILTER (WHERE is_rain_day) AS rain_days,
            count(*) AS total_days,
            round(100.0 * count(*) FILTER (WHERE is_rain_day) / count(*), 1) AS rain_pct,
            round(avg(temperature_max_c) FILTER (WHERE is_rain_day), 1) AS avg_temp_rain_day,
            round(avg(temperature_max_c) FILTER (WHERE NOT is_rain_day), 1) AS avg_temp_non_rain_day
        FROM marts.fct_daily_weather
        GROUP BY city
        ORDER BY city
        """
    )


@app.get("/api/metabase/embed-url")
def metabase_embed_url(user: dict = Depends(get_current_user)):
    return {"url": get_embed_url()}


# ---- Database page (admin only - runs arbitrary SELECTs) ------------------


@app.get("/api/db/tables")
def list_tables(user: dict = Depends(require_admin)):
    return query(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('raw', 'staging', 'marts')
        ORDER BY table_schema, table_name
        """
    )


@app.post("/api/db/query")
def db_query(body: QueryBody, user: dict = Depends(require_admin)):
    try:
        result = run_query(body.sql)
    except HTTPException as exc:
        log_action(user["email"], "sql_query_blocked", user_id=user["id"], detail=f"{body.sql} -- {exc.detail}")
        raise
    log_action(user["email"], "sql_query", user_id=user["id"], detail=body.sql)
    return result


# ---- Audit log (admin only) ------------------------------------------------


@app.get("/api/audit/log")
def audit_log(user: dict = Depends(require_admin)):
    return recent_entries()


# ---- Pipeline status page --------------------------------------------------


@app.get("/api/pipeline/runs")
def pipeline_runs(user: dict = Depends(get_current_user)):
    return pipeline.recent_runs()


@app.get("/api/pipeline/runs/{run_id}/tasks")
def pipeline_run_tasks(run_id: str, user: dict = Depends(get_current_user)):
    return pipeline.tasks_for_run(run_id)


# Must be mounted last - it's a catch-all for "/" and would otherwise shadow
# the /api/* routes above.
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
