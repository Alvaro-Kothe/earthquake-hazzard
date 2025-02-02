import json
import logging
import math
import os
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

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

DB_PATH = "/data/geolocation_cache.db"


@task
def setup_cache():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS geolocation_cache (
            latitude REAL,
            longitude REAL,
            country TEXT,
            continent TEXT,
            PRIMARY KEY (latitude, longitude)
        )
    """)
    conn.commit()
    conn.close()


# https://rosettacode.org/wiki/Haversine_formula#Python
def haversine_distance(lat1, lon1, lat2, lon2):
    earth_radius_km = 6372.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))
    return earth_radius_km * c


def get_cached_location(latitude, longitude, max_distance_km=1):
    conn = sqlite3.connect(DB_PATH)
    conn.create_function("haversine", 4, haversine_distance, deterministic=True)
    point = (latitude, longitude)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT country, continent
        FROM geolocation_cache
        WHERE haversine(latitude, longitude, ?, ?) <= ?
        ORDER BY haversine(latitude, longitude, ?, ?) ASC
        LIMIT 1
        """,
        (*point, max_distance_km, *point),
    )

    result = cursor.fetchone()
    conn.close()

    return result


def save_to_cache(latitude, longitude, country, continent):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO geolocation_cache (latitude, longitude, country, continent) VALUES (?, ?, ?, ?)",
        (latitude, longitude, country, continent),
    )
    conn.commit()
    conn.close()


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


@task(
    retries=3,
    retry_delay=timedelta(seconds=1),
    retry_exponential_backoff=True,
    max_retry_delay=timedelta(seconds=30),
)
def fetch_country_data(row, ti=None):
    import pathlib

    import requests

    earthquake_id, time, longitude, latitude = row

    cached_result = get_cached_location(latitude, longitude)
    if cached_result:
        country, continent = cached_result
        logger.info("Cache hit for (%s, %s): %s", latitude, longitude, country)
        return {
            "earthquake_id": earthquake_id,
            "time": time.isoformat(),
            "country": country,
            "continent": continent,
        }

    ctc_file = pathlib.Path(__file__).parent / "include/country_to_continent.json"
    country_to_continent = json.loads(ctc_file.read_bytes())

    url = "https://nominatim.openstreetmap.org/reverse"
    headers = {"User-Agent": "earthquake-dashboard/1.0", "Accept-Language": "en"}
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "jsonv2",
        "zoom": 3,  # country level
        "addressdetails": 1,
        "extratags": 1,  # contry code
    }
    try:
        response = requests.get(url, params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        country = data.get("address", {}).get("country", UNKNOWN)
        country_id_str = data.get("extratags", {}).get("ISO3166-1:numeric")
        continent = country_to_continent.get(country_id_str)

        save_to_cache(latitude, longitude, country, continent)
        return {
            "earthquake_id": earthquake_id,
            "time": time.isoformat(),
            "country": country,
            "continent": continent,
        }
    except requests.exceptions.RequestException as e:
        # HACK: because of setup and teardown "trigger rule must be ALL_SUCCESS", I can't fail or skip on this error.
        logger.warn(
            "Request error while getting geolocation for (%s, %s): %s",
            latitude,
            longitude,
            e,
        )
        if ti.try_number == ti.max_tries:
            return
        else:
            raise
    except Exception as e:
        logger.error(
            "Error getting geolocation for (%s, %s): %s", latitude, longitude, e
        )
        raise


@task()
def insert_country_data(table_name, data: list[dict[str, str]]):
    hook = BigQueryHook()
    client = hook.get_client()

    client.insert_rows_json(table_name, data)


@dag(
    catchup=False,
    schedule="@daily",
    start_date=datetime(2025, 1, 1),
    max_active_runs=1,
)
def get_country_info():
    create_lat_lon_lookup = setup_cache().as_setup()

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

    fetched_data = fetch_country_data.expand(row=needs_to_insert)
    create_lat_lon_lookup >> fetched_data
    temp_table_data = insert_country_data(table_name=tmp_tbl_name, data=fetched_data)
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

    (
        create_temp_table
        >> temp_table_data
        >> merge_countries_and_continents
        >> delete_temp_table.as_teardown(setups=create_temp_table)
    )


get_country_info()
