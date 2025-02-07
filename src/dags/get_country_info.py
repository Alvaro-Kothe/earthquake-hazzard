import json
import logging
import os
from datetime import timedelta
from uuid import uuid4
import pathlib

from airflow.utils.helpers import chain
import pendulum
from airflow.decorators import dag, task
from airflow.models.xcom_arg import XComArg
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.providers.google.cloud.operators.bigquery import (
    BigQueryCreateEmptyTableOperator,
    BigQueryDeleteTableOperator,
    BigQueryInsertJobOperator,
)
from airflow.sensors.base import PokeReturnValue

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"


def reverse_geocode(
    points: list[tuple[float, float]], max_distance=10000
) -> list[list[str]]:
    """
    Perform a proximity-based reverse geocode.

    :param max_distance: Maximum distance (in meters) for a valid match
    :return: List of list of (country, continent).
    """
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point

    filepath = pathlib.Path(__file__).parent / "include/ne_110m_admin_0_countries.shp"
    world = gpd.read_file(filepath, columns=["NAME", "CONTINENT"])
    world.crs = "EPSG:4326"
    gdf_points = gpd.GeoDataFrame(geometry=[Point(lon, lat) for lon, lat in points])
    gdf_points.crs = "EPSG:4326"

    joined = gpd.sjoin_nearest(
        gdf_points.to_crs(3857),
        world.to_crs(3857),
        max_distance=max_distance,
        distance_col="distance",
        how="left",
    )

    return joined[["NAME", "CONTINENT"]].replace({np.nan: None}).values.tolist()


@task.sensor(poke_interval=120, timeout=60 * 6, mode="reschedule")
def check_country_is_null() -> PokeReturnValue:
    hook = BigQueryHook()
    client = hook.get_client()
    query_check_no_country = """SELECT
        earthquake_id,
        time,
        ST_X(position) AS longitude,
        ST_Y(position) AS latitude
    FROM earthquake.earthquake
    WHERE country IS NULL"""
    query_job = client.query(query_check_no_country)
    rows = query_job.result()
    results = list(rows)
    if results:
        condition_met = True
        op_ret_value = [
            (res.earthquake_id, res.time, res.longitude, res.latitude)
            for res in results
        ]
    else:
        condition_met = False
        op_ret_value = None

    return PokeReturnValue(is_done=condition_met, xcom_value=op_ret_value)


@task()
def get_country(table_name, rows):
    """Insert into temporary table the country and continent data"""
    hook = BigQueryHook()
    client = hook.get_client()
    rows_to_insert: list[dict] = []
    points: list[tuple[float]] = []
    for earthquake_id, time, longitude, latitude in rows:
        rows_to_insert.append(
            {
                "earthquake_id": earthquake_id,
                "time": time.isoformat(),
            }
        )
        points.append((longitude, latitude))
    # Assign country for earthquakes up to 300km from the border
    countries_and_continents = reverse_geocode(points, max_distance=300000)
    for row, cc in zip(rows_to_insert, countries_and_continents):
        country, continent = cc
        row.update(country=country or UNKNOWN, continent=continent)

    client.insert_rows_json(table_name, rows_to_insert)


default_args = {
    "start_date": pendulum.datetime(2025, 1, 1, tz="UTC"),
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
}


@dag(
    default_args=default_args,
    catchup=False,
    schedule="@daily",
    max_active_runs=1,
)
def get_country_info():
    needs_to_insert = check_country_is_null()

    create_temp_table = BigQueryCreateEmptyTableOperator(
        task_id="create_temp_table",
        project_id=os.environ["GCP_PROJECT_NAME"],
        dataset_id="earthquake",
        table_id="countries_staging_" + uuid4().hex,
        schema_fields=[
            {"name": "earthquake_id", "type": "STRING", "mode": "REQUIRED"},
            {"name": "time", "type": "TIMESTAMP", "mode": "REQUIRED"},
            {"name": "country", "type": "STRING", "mode": "REQUIRED"},
            {"name": "continent", "type": "STRING", "mode": "NULLABLE"},
        ],
    )

    @task
    def get_temp_table_name(bq_table):
        return "%s.%s.%s" % (
            bq_table["project_id"],
            bq_table["dataset_id"],
            bq_table["table_id"],
        )

    tmp_tbl_name = get_temp_table_name(XComArg(create_temp_table, "bigquery_table"))

    delete_temp_table = BigQueryDeleteTableOperator(
        task_id="delete_temp_table", deletion_dataset_table=tmp_tbl_name
    )

    merge_query = f"""
    MERGE INTO `earthquake.earthquake` AS target
    USING `{tmp_tbl_name}` AS source
    ON target.earthquake_id = source.earthquake_id
    AND target.time = source.time
    WHEN MATCHED THEN
      UPDATE SET target.country = source.country, target.continent = source.continent
    """

    merge_countries_and_continents = BigQueryInsertJobOperator(
        task_id="merge_countries_and_continents",
        configuration={"query": {"query": merge_query, "useLegacySql": False}},
    )

    chain(
        create_temp_table,
        get_country(table_name=tmp_tbl_name, rows=needs_to_insert),
        merge_countries_and_continents,
        delete_temp_table.as_teardown(setups=create_temp_table),
    )


get_country_info()
