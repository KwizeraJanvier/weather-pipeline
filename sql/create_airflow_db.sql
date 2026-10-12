-- Docker setup only: Airflow keeps its own metadata (DAG runs, task state)
-- in a separate database on the same Postgres container as the warehouse.
-- The cloud setup doesn't use this - there, the pipeline runs on GitHub
-- Actions instead of Airflow.
CREATE DATABASE airflow_meta;
