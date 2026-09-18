import sys
from datetime import datetime

sys.path.insert(0, "/opt/airflow/extraction")

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

from fetch_weather import run as run_extraction

default_args = {"owner": "data-eng", "retries": 1}

with DAG(
    dag_id="weather_pipeline",
    description="Fetch daily weather history and transform it with dbt",
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
        bash_command=(
            "cd /opt/airflow/dbt/weather_dbt && "
            "dbt run --profiles-dir /opt/airflow/dbt/weather_dbt"
        ),
    )

    extract >> transform
