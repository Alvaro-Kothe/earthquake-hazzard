import json
import logging
import math
import sqlite3
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.providers.google.cloud.operators.bigquery import BigQueryInsertJobOperator
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


@task.sensor(poke_interval=120, timeout=60 * 30, mode="reschedule")
def check_country_is_null() -> PokeReturnValue:
    hook = BigQueryHook()
    client = hook.get_client()
    query_check_no_country = """SELECT
        earthquake_id,
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
            (res.earthquake_id, res.longitude, res.latitude) for res in results
        ]
    else:
        condition_met = False
        op_ret_value = None

    return PokeReturnValue(is_done=condition_met, xcom_value=op_ret_value)


@task
def create_temp_table():
    import uuid

    from google.cloud import bigquery

    hook = BigQueryHook()
    client = hook.get_client()

    table_prefix = "earthquake.countries_staging_"
    table_name = table_prefix + uuid.uuid4().hex
    query_create_table = f"""
    CREATE TABLE `{table_name}` (earthquake_id STRING, country STRING, continent STRING)
    OPTIONS(expiration_timestamp = @expiration)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "expiration", "TIMESTAMP", datetime.now() + timedelta(hours=3)
            ),
        ]
    )

    client.query_and_wait(query_create_table, job_config=job_config)
    logger.info("Created table %s", table_name)

    return table_name


@task(
    retries=3,
    retry_delay=timedelta(seconds=1),
    retry_exponential_backoff=True,
    max_retry_delay=timedelta(seconds=30),
)
def fetch_country_data(row):
    import pathlib

    import requests

    earthquake_id, longitude, latitude = row

    cached_result = get_cached_location(latitude, longitude)
    if cached_result:
        country, continent = cached_result
        logger.info("Cache hit for (%s, %s): %s", latitude, longitude, country)
        return {
            "earthquake_id": earthquake_id,
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
            "country": country,
            "continent": continent,
        }
    except Exception as e:
        logger.error(
            "Error fetching country data for (%s, %s): %s", latitude, longitude, e
        )
        raise


@task(trigger_rule="none_failed_min_one_success")
def insert_country_data(table_name, data: list[dict[str, str]]):
    hook = BigQueryHook()
    client = hook.get_client()

    client.insert_rows_json(table_name, data)


@dag(
    catchup=False, schedule="@daily", start_date=datetime(2025, 1, 1), max_active_runs=1
)
def get_country_info():
    create_lat_lon_lookup = setup_cache()

    needs_to_insert = check_country_is_null()
    temp_table_name = create_temp_table()
    fetched_data = fetch_country_data.expand(row=needs_to_insert)
    create_lat_lon_lookup >> fetched_data
    temp_table_data = insert_country_data(table_name=temp_table_name, data=fetched_data)

    merge_query = f"""
    MERGE INTO `earthquake.earthquake` AS target
    USING `{temp_table_name}` AS source
    ON target.earthquake_id = source.earthquake_id
    WHEN MATCHED THEN
      UPDATE SET target.country = source.country, target.continent = source.continent
    """

    insert_country_cont = BigQueryInsertJobOperator(
        task_id="insert_country_cont",
        configuration={"query": {"query": merge_query, "useLegacySql": False}},
    )

    temp_table_data >> insert_country_cont


get_country_info()
