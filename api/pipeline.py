"""Run history for the Data Pipeline page.

The same pipeline runs in two environments, and where its history lives
differs, so this reads from whichever PIPELINE_SOURCE says:

- "github" (default; the deployed cloud app): the pipeline runs as a
  scheduled GitHub Actions workflow (.github/workflows/daily_pipeline.yml),
  so history comes from GitHub's Actions API. Each workflow step is shown
  as a "task".
- "airflow" (the local Docker stack): the pipeline is an Airflow DAG, whose
  metadata lives in the airflow_meta database on the same Postgres
  container as the warehouse.

Both return the same shapes, so the frontend doesn't care which it's using:
runs are {run_id, state, run_type, start_date, end_date}, tasks are
{task_id, state, start_date, end_date}.
"""
import os

import psycopg2.extras
import requests

import db

PIPELINE_SOURCE = os.environ.get("PIPELINE_SOURCE", "github")

# ---- GitHub Actions ---------------------------------------------------------

GITHUB_OWNER = os.environ.get("GITHUB_REPO_OWNER", "KwizeraJanvier")
GITHUB_REPO = os.environ.get("GITHUB_REPO_NAME", "weather-pipeline")
WORKFLOW_FILE = "daily_pipeline.yml"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional - raises the rate limit
API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def _github_runs(limit: int) -> list[dict]:
    resp = requests.get(
        f"{API_BASE}/actions/workflows/{WORKFLOW_FILE}/runs",
        headers=_github_headers(),
        params={"per_page": limit},
        timeout=10,
    )
    resp.raise_for_status()
    return [
        {
            "run_id": str(r["id"]),
            "state": r["conclusion"] or r["status"],
            "run_type": r["event"],
            "start_date": r["run_started_at"],
            "end_date": r["updated_at"] if r["status"] == "completed" else None,
        }
        for r in resp.json()["workflow_runs"]
    ]


def _github_tasks(run_id: str) -> list[dict]:
    resp = requests.get(f"{API_BASE}/actions/runs/{run_id}/jobs", headers=_github_headers(), timeout=10)
    resp.raise_for_status()
    return [
        {
            "task_id": step["name"],
            "state": step["conclusion"] or step["status"],
            "start_date": step["started_at"],
            "end_date": step["completed_at"],
        }
        for job in resp.json()["jobs"]
        for step in job["steps"]
    ]


# ---- Airflow (local Docker stack) -------------------------------------------

AIRFLOW_DAG_ID = "weather_pipeline"
AIRFLOW_META_DB = os.environ.get("AIRFLOW_META_DB_NAME", "airflow_meta")


def _airflow_query(sql: str, params: tuple) -> list[dict]:
    conn = db._connect(
        os.environ.get("WAREHOUSE_DB_USER", "warehouse"),
        os.environ.get("WAREHOUSE_DB_PASSWORD", "warehouse"),
        dbname=AIRFLOW_META_DB,
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def _airflow_runs(limit: int) -> list[dict]:
    return _airflow_query(
        """
        SELECT run_id, state, run_type, start_date, end_date
        FROM dag_run
        WHERE dag_id = %s
        ORDER BY execution_date DESC
        LIMIT %s
        """,
        (AIRFLOW_DAG_ID, limit),
    )


def _airflow_tasks(run_id: str) -> list[dict]:
    return _airflow_query(
        """
        SELECT task_id, state, start_date, end_date
        FROM task_instance
        WHERE dag_id = %s AND run_id = %s
        ORDER BY start_date
        """,
        (AIRFLOW_DAG_ID, run_id),
    )


# ---- Public API ---------------------------------------------------------------


def recent_runs(limit: int = 10) -> list[dict]:
    return _airflow_runs(limit) if PIPELINE_SOURCE == "airflow" else _github_runs(limit)


def tasks_for_run(run_id: str) -> list[dict]:
    return _airflow_tasks(run_id) if PIPELINE_SOURCE == "airflow" else _github_tasks(run_id)
