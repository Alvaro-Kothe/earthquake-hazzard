import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any

from airflow.utils.helpers import chain
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
from datetime import UTC

from shapely.geometry import Point
from upath import UPath

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"

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
    {
        "name": "country",
        "type": "STRING",
        "mode": "NULLABLE",
    },
    {
        "name": "continent",
        "type": "STRING",
        "mode": "NULLABLE",
    },
]


@task(max_active_tis_per_dag=1)
def download_shapefile_to_gcs(file_path: UPath):
    import tempfile

    import requests

    if file_path.exists():
        logger.info("%s already exists", file_path)
        return

    data_url = (
        "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"
    )

    with requests.get(data_url, stream=True) as response:
        response.raise_for_status()
        with tempfile.TemporaryFile() as shape_zip:
            for chunk in response.iter_content(chunk_size=1024):
                shape_zip.write(chunk)

            shape_zip.seek(0)  # Move pointer to start of buffer

            file_path.write_bytes(shape_zip.read())

            logger.info(
                "Written %.2f KiB into %s", shape_zip.tell() / (1024.0), file_path
            )


def reverse_geocode(
    points: list[Point],
    shapefile_path: UPath,
    max_distance=10000,
) -> list[list[str]]:
    """
    Perform a proximity-based reverse geocode.

    :param max_distance: Maximum distance (in meters) for a valid match
    :return: List of list of (country, continent).
    """
    import geopandas as gpd
    import numpy as np

    with shapefile_path.open("rb") as shapefile:
        world = gpd.read_file(shapefile, columns=["NAME", "CONTINENT"])
    gdf_points = gpd.GeoDataFrame(geometry=points)
    gdf_points.set_crs(4326, inplace=True)

    joined = gpd.sjoin_nearest(
        gdf_points.to_crs(3857),
        world.to_crs(3857),
        max_distance=max_distance,
        distance_col="distance",
        how="left",
    )

    return joined[["NAME", "CONTINENT"]].replace({np.nan: None}).values.tolist()


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
) -> UPath:
    import requests

    base_path = ObjectStoragePath(
        f"gs://{Variable.get('gcp_bucket')}/earthquakes", conn_id="google_cloud_default"
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
    fname = f"earthquake_{data_interval_start.format('YYYYMMDD')}-{data_interval_end.format('YYYYMMDD')}.json"
    path = base_path / fname

    path.write_bytes(response.content)
    logger.info("Sent data to %s", str(path))

    return path  # pyright: ignore [reportReturnType]


@task()
def import_to_bigquery(table_name: str, features_path: UPath, shapefile_path: UPath):
    import json

    hook = BigQueryHook()
    client = hook.get_client()

    rows_to_insert: list[dict[str, Any]] = []
    points: list[Point] = []

    with features_path.open() as f:
        features = json.load(f)["features"]

    for feature in features:
        id = feature["id"]
        lon, lat, depth = feature["geometry"]["coordinates"]
        properties = feature["properties"]
        magnitude = properties["mag"]
        time = datetime.fromtimestamp(properties["time"] / 1000.0, UTC)
        alert = properties["alert"]
        significance = properties["sig"]

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
        points.append(Point(lon, lat))

    countries_and_continents = reverse_geocode(
        points, shapefile_path=shapefile_path, max_distance=300000
    )
    for row, cc in zip(rows_to_insert, countries_and_continents):
        country, continent = cc
        row.update(country=country or UNKNOWN, continent=continent)

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
          INSERT (earthquake_id, position, depth, magnitude, time, alert, significance, country, continent)
          VALUES (source.earthquake_id, source.position, source.depth, source.magnitude, source.time, source.alert, source.significance, source.country, source.continent);
    """
    merge_from_temp = BigQueryInsertJobOperator(
        task_id="merge_from_temp",
        configuration={"query": {"query": merge_query, "useLegacySql": False}},
    )

    shapefile_path = ObjectStoragePath(
        "gs://{{ var.value.get('gcp_bucket') }}/shapefiles/ne_110m_admin_0_countries.zip",
        conn_id="google_cloud_default",
    )
    downloaded_data_path = download_and_export_to_gcs()
    fill_temp_table = import_to_bigquery(
        table_name=tmp_tbl_name,
        features_path=downloaded_data_path,
        shapefile_path=shapefile_path,
    )
    chain(
        download_shapefile_to_gcs(shapefile_path),
        fill_temp_table,
        merge_from_temp,
        delete_temp_table.as_teardown(setups=temp_table),
    )


get_earthquake_data()
