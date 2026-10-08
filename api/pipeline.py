import os

import requests

# The pipeline used to run on a local Airflow instance, whose SQLite
# metadata file this module read directly. It now runs via GitHub Actions
# instead (see .github/workflows/daily_pipeline.yml) - the author's network
# blocks outbound Postgres entirely, which made a locally-hosted Airflow
# instance unable to reach a cloud database at all. This reads run history
# from GitHub's own API instead, keeping the exact same response shape so
# the frontend needed no changes.
GITHUB_OWNER = os.environ.get("GITHUB_REPO_OWNER", "KwizeraJanvier")
GITHUB_REPO = os.environ.get("GITHUB_REPO_NAME", "weather-pipeline")
WORKFLOW_FILE = "daily_pipeline.yml"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional - raises the rate limit
API_BASE = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def recent_runs(limit: int = 10) -> list[dict]:
    resp = requests.get(
        f"{API_BASE}/actions/workflows/{WORKFLOW_FILE}/runs",
        headers=_headers(),
        params={"per_page": limit},
        timeout=10,
    )
    resp.raise_for_status()
    runs = resp.json()["workflow_runs"]
    return [
        {
            "run_id": str(r["id"]),
            "state": r["conclusion"] or r["status"],
            "run_type": r["event"],
            "start_date": r["run_started_at"],
            "end_date": r["updated_at"] if r["status"] == "completed" else None,
        }
        for r in runs
    ]


def tasks_for_run(run_id: str) -> list[dict]:
    resp = requests.get(f"{API_BASE}/actions/runs/{run_id}/jobs", headers=_headers(), timeout=10)
    resp.raise_for_status()
    tasks = []
    for job in resp.json()["jobs"]:
        for step in job["steps"]:
            tasks.append(
                {
                    "task_id": step["name"],
                    "state": step["conclusion"] or step["status"],
                    "start_date": step["started_at"],
                    "end_date": step["completed_at"],
                }
            )
    return tasks
