import os
from unittest.mock import MagicMock, patch

import pendulum
import pytest
import json

os.environ["GCP_PROJECT_NAME"] = "test-project"

from src.dags.get_earthquake_data import download_and_export_to_gcs, import_to_bigquery


@pytest.fixture
def mock_variable_get():
    with patch(
        "src.dags.get_earthquake_data.Variable.get", return_value="test-bucket"
    ) as mock:
        yield mock


@pytest.fixture
def mock_ObjectStoragePath():
    with patch("src.dags.get_earthquake_data.ObjectStoragePath") as mock:
        mock_path = MagicMock()
        mock.return_value = mock_path
        mock_path.__truediv__.return_value = MagicMock()
        yield mock


@pytest.fixture
def mock_requests_get():
    with patch("requests.get") as mock:  # Patch 'requests.get' globally
        mock_response = MagicMock()
        mock_response.content = b'{"features": []}'
        mock_response.raise_for_status = (
            MagicMock()
        )  # Ensure `raise_for_status` does nothing
        mock.return_value = mock_response
        yield mock


@pytest.fixture
def mock_bigquery_hook():
    with patch("src.dags.get_earthquake_data.BigQueryHook") as mock_hook:
        mock_client = MagicMock()
        mock_hook.return_value.get_client.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_object_storage_path_written():
    with patch("src.dags.get_earthquake_data.ObjectStoragePath") as mock_path:
        mock_file = MagicMock()
        mock_file.__enter__.return_value.read.return_value = json.dumps(
            {
                "features": [
                    {
                        "id": "eq123",
                        "geometry": {"coordinates": [-120.5, 34.2, 10.0]},
                        "properties": {
                            "mag": 5.4,
                            "time": 1700000000000,  # Milliseconds since epoch
                            "alert": None,
                            "sig": 1,
                        },
                    }
                ]
            }
        )
        mock_path_instance = mock_path.return_value
        mock_path_instance.open.return_value = mock_file
        yield mock_path_instance


def test_download_and_export_to_gcs(
    mock_variable_get, mock_ObjectStoragePath, mock_requests_get
):
    mock_path = mock_ObjectStoragePath.return_value
    data_interval_start = pendulum.datetime(2025, 1, 1)
    data_interval_end = pendulum.datetime(2025, 1, 2)
    expected_filename = "earthquake_20250101-20250102.json"

    result = download_and_export_to_gcs.function(data_interval_start, data_interval_end)

    mock_requests_get.assert_called_once_with(
        "https://earthquake.usgs.gov/fdsnws/event/1/query",
        params={
            "starttime": "2025-01-01T00:00:00Z",
            "endtime": "2025-01-02T00:00:00Z",
            "format": "geojson",
        },
    )
    mock_variable_get.assert_called_once()
    mock_ObjectStoragePath.assert_called_once_with(
        "gs://test-bucket/", conn_id="google_cloud_default"
    )
    mock_path.__truediv__.assert_called_once_with(expected_filename)
    mock_filepath = mock_path / expected_filename
    mock_filepath.write_bytes.assert_called_once_with(b'{"features": []}')
    assert result == mock_filepath


def test_import_to_bigquery_success(mock_bigquery_hook, mock_object_storage_path_written):
    table_name = "my-project.my-dataset.my-table"

    # Call the function directly, bypassing Airflow
    mock_bigquery_hook.insert_rows_json.return_value = []
    import_to_bigquery.function(table_name, mock_object_storage_path_written)

    # Expected data transformation
    expected_rows = [
        {
            "earthquake_id": "eq123",
            "position": "POINT(-120.5 34.2)",
            "depth": 10.0,
            "magnitude": 5.4,
            "time": "2023-11-14T22:13:20+00:00",
            "alert": None,
            "significance": 1,
        }
    ]

    # Ensure BigQuery insert was called correctly
    mock_bigquery_hook.insert_rows_json.assert_called_once_with(
        table_name, expected_rows
    )


def test_import_to_bigquery_failure(mock_bigquery_hook, mock_object_storage_path_written):
    table_name = "earthquake_table"
    mock_bigquery_hook.insert_rows_json.return_value = [
        {"error": "some error"}
    ]  # Simulate failure

    with pytest.raises(RuntimeError, match="some error"):
        import_to_bigquery.function(table_name, mock_object_storage_path_written)
