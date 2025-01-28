import logging
from datetime import datetime

from airflow.decorators import dag, task
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook
from airflow.sensors.base import PokeReturnValue

logger = logging.getLogger(__name__)

UNKNOWN = "Unknown"


@task.sensor(poke_interval=60, timeout=60 * 30, mode="poke")
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
def get_country(row):
    import json
    import pathlib

    import requests
    from google.cloud import bigquery

    earthquake_id, longitude, latitude = row
    ctc_file = pathlib.Path(__file__).parent / "include/country_to_continent.json"
    country_to_continent = json.loads(ctc_file.read_bytes())

    hook = BigQueryHook()
    client = hook.get_client()
    table_name = "earthquake.earthquake"
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
        country_id_str = data.get("extratags", {}).get("ISO3166-1:numeric")
        continent = country_to_continent.get(country_id_str)
        assert continent is not None or country == UNKNOWN
        if country == UNKNOWN:
            logger.info(
                "No country information found for coordinates: (%s, %s). Likely in the sea.",
                latitude,
                longitude,
            )

        logger.debug(
            "Country information retrieved successfully for (%s, %s): %s (ID: %s)",
            latitude,
            longitude,
            country,
            country_id_str,
        )

        query_insert = f"""
        UPDATE {table_name}
        SET country = @country, continent = @continent
        WHERE earthquake_id = @earthquake_id
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("country", "STRING", country),
                bigquery.ScalarQueryParameter("continent", "STRING", continent),
                bigquery.ScalarQueryParameter("earthquake_id", "STRING", earthquake_id),
            ]
        )
        logger.debug("Sent query: %s", query_insert)
        add_country_job = client.query(query_insert, job_config=job_config)
        add_country_job.result(0)
        logger.info(
            "Set earthquake_id %s: country='%s' and continent='%s'",
            earthquake_id,
            country,
            continent or "NULL",
        )
    except Exception as e:
        logger.error("Error fetching or inserting country data: %s", e)
        raise


@dag(catchup=False, schedule="@daily", start_date=datetime(2025, 1, 1))
def get_country_info():
    needs_to_insert = check_country_is_null()
    get_country.expand(row=needs_to_insert)


get_country_info()
