FROM apache/airflow:2.10.4-python3.12
RUN python -m venv ${AIRFLOW_HOME}/virtualvenv/dbt_venv && \
    ${AIRFLOW_HOME}/virtualvenv/dbt_venv/bin/python -m pip install --no-cache-dir "dbt-bigquery>=1.8.3" "dbt-core>=1.8.7"
RUN pip install --no-cache-dir astronomer-cosmos geopandas shapely
