import logging
from datetime import timedelta

import pendulum
from airflow.decorators import dag, task
from airflow.io.path import ObjectStoragePath
from airflow.models import Variable
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator

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
        "limit": 2,  # TODO: Change for final version
    }
    response = requests.get(api_url, params=params)
    response.raise_for_status()

    logger.info("Downloaded Data")
    fname = f"earthquake_{data_interval_start.format("YYYYMMDD")}-{data_interval_end.format("YYYYMMDD")}.json"
    path = base_path / fname

    path.write_bytes(response.content)
    logger.info("Sent data to %s", str(path))

    return path  # pyright: ignore [reportReturnType]


@task(do_xcom_push=True)
def transform_features(path: ObjectStoragePath):
    import json
    from datetime import datetime

    result = []

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

        result.append(
            {
                "earthquake_id": id,
                "latitude": lat,
                "longitude": lon,
                "depth": depth,
                "magnitude": magnitude,
                "time": time,
                "alert": alert or "NULL",
                "significance": significance,
            }
        )

    return result


@dag(
    default_args=default_args,
    description="Download earthquake data and insert into data lake and warehouse",
    schedule="@daily",
    catchup=False,
    tags=["earthquake"],
)
def import_earthquake_data():
    load_to_bq = BigQueryInsertJobOperator(
        task_id="load_to_bq",
        configuration={
            "query": {
                "query": "{% include 'sql/insert_earthquake.sql' %}",
                "useLegacySql": False,
                "priority": "BATCH",
            }
        },
    )
    transform_features(download_and_export_to_gcs()) >> load_to_bq


import_earthquake_data()
