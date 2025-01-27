import logging
from datetime import datetime, timedelta

from airflow import XComArg
from airflow.decorators import dag, task
from airflow.providers.common.sql.sensors.sql import SqlSensor
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.sensors.base import PokeReturnValue

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"


@task.sensor(poke_interval=60, timeout=60 * 30, mode="poke")
def check_null_country_id() -> PokeReturnValue:
    hook = BigQueryHook()
    client = hook.get_client()
    query_check_no_country = """SELECT 
        earthquake_id, 
        ST_X(position) AS longitude, 
        ST_Y(position) AS latitude 
    FROM earthquake.earthquake 
    WHERE country_id IS NULL"""
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
def get_country(row):
    import requests

    earthquake_id, longitude, latitude = row

    hook = BigQueryHook()
    client = hook.get_client()
    table_name = "earthquake.countries"
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
        response = requests.get(url, params, headers=headers)
        response.raise_for_status()

        data = response.json()
        country = data.get("address", {}).get("country", UNKNOWN)
        country_id_str = data.get("extratags", {}).get("ISO3166-1:numeric", "-1")
        country_id = int(country_id_str)
        if country == UNKNOWN:
            logger.info(
                "No country information found for coordinates: (%s, %s). Likely in the sea.",
                latitude,
                longitude,
            )

        # Check if the country already exists in the lookup table
        query_check = f"""
            SELECT country_id
            FROM {table_name}
            WHERE country_id = {country_id}
        """
        logger.debug("Sent query: %s", query_check)
        query_job = client.query(query_check)
        rows = query_job.result()
        results = list(rows)

        if not results:
            insert_query = f"""
                INSERT INTO {table_name} (country_id, country_name)
                VALUES ({country_id}, '{country}')
            """
            logger.debug("Sent query: %s", insert_query)
            ins_in_ctry_tbl_jb = client.query(insert_query)
            ins_in_ctry_tbl_jb.result(0)

        logger.debug(
            "Country information retrieved successfully for (%s, %s): %s (ID: %s)",
            latitude,
            longitude,
            country,
            country_id,
        )

        query_insert = f"""
        UPDATE earthquake.earthquake 
        SET country_id = {country_id} 
        WHERE earthquake_id = '{earthquake_id}'
        """
        logger.debug("Sent query: %s", query_insert)
        add_country_job = client.query(query_insert)
        add_country_job.result(0)
        logger.info("Set earthquake_id %s country to %d", country_id)
    except Exception as e:
        logger.error("Error fetching or inserting country data: %s", e)
        raise


@dag(catchup=False, schedule="@daily", start_date=datetime(2025, 1, 1))
def get_country_info():
    needs_to_insert = check_null_country_id()
    get_country.expand(row=needs_to_insert)


get_country_info()
