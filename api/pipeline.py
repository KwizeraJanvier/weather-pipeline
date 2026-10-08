import sqlite3
from pathlib import Path

AIRFLOW_DB = Path(__file__).resolve().parent.parent / "airflow_home" / "airflow.db"
DAG_ID = "weather_pipeline"


def _connect():
    # mode=ro: never write to Airflow's own database, and avoids fighting
    # the scheduler for a write lock on SQLite's single-writer file.
    return sqlite3.connect(f"file:{AIRFLOW_DB}?mode=ro", uri=True)


def recent_runs(limit: int = 10) -> list[dict]:
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT run_id, state, run_type, start_date, end_date, execution_date
            FROM dag_run
            WHERE dag_id = ?
            ORDER BY execution_date DESC
            LIMIT ?
            """,
            (DAG_ID, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def tasks_for_run(run_id: str) -> list[dict]:
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT task_id, state, start_date, end_date, try_number
            FROM task_instance
            WHERE dag_id = ? AND run_id = ?
            ORDER BY start_date
            """,
            (DAG_ID, run_id),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
