FROM apache/airflow:2.9.3-python3.11

COPY extraction/requirements.txt /tmp/extraction-requirements.txt
RUN pip install --no-cache-dir -r /tmp/extraction-requirements.txt \
    && pip install --no-cache-dir dbt-postgres==1.8.*
