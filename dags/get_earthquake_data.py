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
UNKNOWN = "Unknown"


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


# TODO: This should run in another dag, using expand
@task
def get_country(latitude: str, longitude: str) -> str:
    # TODO: Import all data into the database, without geolocation
    # TODO: Have a separate dag/function that fills the country information where needed.

    # TODO: Get the country, using the coordinates, where the earthquake occurred. (store the encoding, ISO 3166-1 alpha-3 code; 3-digit country-code; country name) # check if 3-digit country code can be stored as i16
    import requests

    url = "https://nominatim.openstreetmap.org/reverse"
    headers = {"User-Agent": "earthquake-dashboard/1.0", "Accept-Language": "en"}
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "json",
        "zoom": 3,  # country level
        "addressdetails": 1,
    }
    try:
        response = requests.get(url, params, headers=headers)
        response.raise_for_status()

        data = response.json()
        address = data.get("address", {})
        country = address.get("country", UNKNOWN)

        return country
    except Exception as e:
        logger.error("Error fetching location data: %s", e)
        raise


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
