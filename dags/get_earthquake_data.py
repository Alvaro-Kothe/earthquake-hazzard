from datetime import timedelta
from airflow.decorators import dag
from airflow.decorators import task
from airflow.models import Variable
import pendulum
import logging
from airflow.io.path import ObjectStoragePath

logger = logging.getLogger(__name__)


# TODO: Manipulate the data from the geojson to extract:
#   0. id, in features[idx].id, This should have the unique constraint
#   1. The coordinates, in features[idx].geometry[0..1]
#   2. The depth, in features[idx].geometry[2]
#   3. The magnitude, in features[idx].properties.mag
#   4. The time, in features[idx].properties.time, this is in long int with offset from 1970-01-01T00:00:00.000Z, must convert from posix time to timestamp
#   5. alert, in features[idx].properties.alert, This is nullable
#   6. significance, in features[idx].properties.sig
# TODO: Get the country, using the coordinates, where the earthquake occurred. (store the encoding, ISO 3166-1 alpha-3 code; 3-digit country-code; country name) # check if 3-digit country code can be stored as i16
# TODO: Add a foreign key into the bigquery database, and the lookup table
# TODO: https://airflow.apache.org/docs/apache-airflow-providers-google/stable/connections/gcp.html
# TODO: Use secrets backend https://airflow.apache.org/docs/apache-airflow-providers-google/stable/secrets-backends/google-cloud-secret-manager-backend.html

default_args = {
    "start_date": pendulum.datetime(2025, 1, 1, tz="UTC"),
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=1),
}


# pyright: reportOptionalMemberAccess=false
@dag(
    default_args=default_args,
    description="Download earthquake data and insert into data lake and warehouse",
    schedule="@daily",
    catchup=False,
    tags=["earthquake"],
)
def import_earthquake_data():
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

    download_and_export_to_gcs()


import_earthquake_data()
