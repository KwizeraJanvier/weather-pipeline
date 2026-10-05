import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXTRACTION_DIR = PROJECT_ROOT / "extraction"
FORECAST_DIR = PROJECT_ROOT / "forecast"
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt" / "weather_dbt"
DBT_BIN = PROJECT_ROOT / ".venv" / "bin" / "dbt"

sys.path.insert(0, str(EXTRACTION_DIR))
sys.path.insert(0, str(FORECAST_DIR))

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from fetch_weather import run as run_extraction
from forecast_weather import run as run_forecast

default_args = {"owner": "data-eng", "retries": 1}

with DAG(
    dag_id="weather_pipeline",
    description="Fetch daily weather history, transform it with dbt, and forecast a few days ahead",
    default_args=default_args,
    start_date=datetime(2026, 9, 1),
    schedule_interval="@daily",
    catchup=False,
    tags=["weather", "etl"],
) as dag:

    extract = PythonOperator(
        task_id="extract_weather",
        python_callable=run_extraction,
    )

    transform = BashOperator(
        task_id="dbt_run",
        bash_command=f'cd "{DBT_PROJECT_DIR}" && "{DBT_BIN}" run --profiles-dir "{DBT_PROJECT_DIR}"',
    )

    forecast = PythonOperator(
        task_id="forecast_weather",
        python_callable=run_forecast,
    )

    extract >> transform >> forecast
