import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

import pendulum
from airflow.decorators import dag, task
from airflow.io.path import ObjectStoragePath
from airflow.models import Variable
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.providers.google.cloud.operators.bigquery import (
    BigQueryInsertJobOperator,
)

logger = logging.getLogger(__name__)

# pyright: reportOptionalMemberAccess=false

default_args = {
    "start_date": pendulum.datetime(2025, 1, 1, tz="UTC"),
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
}


@task
def download_and_export_to_gcs(
    data_interval_start: pendulum.DateTime | None = None,
    data_interval_end: pendulum.DateTime | None = None,
) -> ObjectStoragePath:
    import requests

    base_path = ObjectStoragePath(
        f"gs://{Variable.get('gcp_bucket')}/", conn_id="google_cloud_default"
    )

    api_url = "https://earthquake.usgs.gov/fdsnws/event/1/query"
    params = {
        "starttime": data_interval_start.to_iso8601_string(),
        "endtime": data_interval_end.to_iso8601_string(),
        "format": "geojson",  # TODO: If OOM, consider a different format
    }
    response = requests.get(api_url, params=params)
    response.raise_for_status()

    logger.info("Downloaded Data")
    fname = f"earthquake_{data_interval_start.format("YYYYMMDD")}-{data_interval_end.format("YYYYMMDD")}.json"
    path = base_path / fname

    path.write_bytes(response.content)
    logger.info("Sent data to %s", str(path))

    return path  # pyright: ignore [reportReturnType]


@task()
def import_to_bigquery(table_name: str, path: ObjectStoragePath):
    import json
    from datetime import datetime

    hook = BigQueryHook()
    client = hook.get_client()

    rows_to_insert: list[dict[str, Any]] = []

    with path.open() as f:
        features = json.load(f)["features"]

    for feature in features:
        id = feature["id"]
        lon, lat, depth = feature["geometry"]["coordinates"]
        properties = feature["properties"]
        magnitude = properties["mag"]
        time = datetime.utcfromtimestamp(properties["time"] / 1000.0)
        alert = properties["alert"]
        significance = properties["sig"]

        logger.info(
            "going to insert %s, POINT(%.3f %.3f), %.2f, %s, %s, %d",
            id,
            lon,
            lat,
            depth,
            magnitude,
            time.isoformat(),
            alert,
            significance,
        )
        rows_to_insert.append(
            {
                "earthquake_id": id,
                "position": f"POINT({lon} {lat})",
                "depth": depth,
                "magnitude": magnitude,
                "time": time.isoformat(),
                "alert": alert,
                "significance": significance,
            }
        )

    errors = client.insert_rows_json(table_name, rows_to_insert)
    if errors == []:
        logger.info("New rows have been added.")
    else:
        logger.error("Encountered errors while inserting rows: %s", errors)

    assert errors == []


@task
def create_temp_table():
    from google.cloud import bigquery

    hook = BigQueryHook()
    client = hook.get_client()

    table_prefix = "earthquake.earthquake_staging_"
    table_name = table_prefix + uuid.uuid4().hex
    query_create_table = f"""
    CREATE TABLE `{table_name}`
    LIKE earthquake.earthquake
    OPTIONS(expiration_timestamp = @expiration)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "expiration", "TIMESTAMP", datetime.now() + timedelta(days=2)
            ),
        ]
    )

    client.query_and_wait(query_create_table, job_config=job_config)
    return table_name


@dag(
    default_args=default_args,
    description="Download earthquake data and insert into data lake and warehouse",
    schedule="@daily",
    catchup=False,
    tags=["earthquake"],
)
def get_earthquake_data():
    temp_table = create_temp_table()
    merge_from_temp = BigQueryInsertJobOperator(
        task_id="merge_from_temp",
        configuration={
            "query": {
                "query": "{% include 'sql/insert_earthquake.sql' %}",
                "useLegacySql": False,
                "priority": "BATCH",
            }
        },
    )

    downloaded_data_path = download_and_export_to_gcs()
    filled_temp_table = import_to_bigquery(
        table_name=temp_table, path=downloaded_data_path
    )
    filled_temp_table >> merge_from_temp


get_earthquake_data()
