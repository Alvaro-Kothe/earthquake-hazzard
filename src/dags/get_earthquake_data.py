import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

import pendulum
from airflow import XComArg
from airflow.decorators import dag, task
from airflow.io.path import ObjectStoragePath
from airflow.models import Variable
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.providers.google.cloud.operators.bigquery import (
    BigQueryCreateEmptyTableOperator,
    BigQueryDeleteTableOperator,
    BigQueryInsertJobOperator,
)

logger = logging.getLogger(__name__)


schema_fields = [
    {
        "name": "earthquake_id",
        "type": "STRING",
        "mode": "REQUIRED",
    },
    {
        "name": "position",
        "type": "GEOGRAPHY",
        "mode": "REQUIRED",
    },
    {
        "name": "depth",
        "type": "FLOAT",
        "mode": "REQUIRED",
    },
    {
        "name": "magnitude",
        "type": "FLOAT",
        "mode": "REQUIRED",
    },
    {
        "name": "time",
        "type": "TIMESTAMP",
        "mode": "REQUIRED",
    },
    {
        "name": "alert",
        "type": "STRING",
        "mode": "NULLABLE",
    },
    {
        "name": "significance",
        "type": "INTEGER",
        "mode": "REQUIRED",
    },
]

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
        raise RuntimeError(errors)


@dag(
    default_args=default_args,
    description="Download earthquake data and insert into data lake and warehouse",
    schedule="@daily",
    catchup=False,
    tags=["earthquake"],
)
def get_earthquake_data():
    temp_table = BigQueryCreateEmptyTableOperator(
        task_id="create_temp_table",
        project_id=os.environ["GCP_PROJECT_NAME"],
        dataset_id="earthquake",
        table_id="earthquake_staging_" + uuid.uuid4().hex,
        schema_fields=schema_fields,
    )

    @task
    def get_temp_table_name(bq_table):
        return "%s.%s.%s" % (
            bq_table["project_id"],
            bq_table["dataset_id"],
            bq_table["table_id"],
        )

    tmp_tbl_name = get_temp_table_name(XComArg(temp_table, "bigquery_table"))

    delete_temp_table = BigQueryDeleteTableOperator(
        task_id="delete_temp_table", deletion_dataset_table=tmp_tbl_name
    )

    merge_query = f"""
        MERGE INTO `{os.environ["GCP_PROJECT_NAME"]}.earthquake.earthquake` AS target
        USING {tmp_tbl_name} AS source
        ON target.earthquake_id = source.earthquake_id
        AND target.time = source.time
        WHEN NOT MATCHED THEN
          INSERT (earthquake_id, position, depth, magnitude, time, alert, significance)
          VALUES (source.earthquake_id, source.position, source.depth, source.magnitude, source.time, source.alert, source.significance);
    """
    merge_from_temp = BigQueryInsertJobOperator(
        task_id="merge_from_temp",
        configuration={"query": {"query": merge_query, "useLegacySql": False}},
    )

    downloaded_data_path = download_and_export_to_gcs()
    filled_temp_table = import_to_bigquery(
        table_name=tmp_tbl_name, path=downloaded_data_path
    )
    (
        filled_temp_table
        >> merge_from_temp
        >> delete_temp_table.as_teardown(setups=temp_table)
    )


get_earthquake_data()
