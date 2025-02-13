"""
## Run dbt cli from the ./dbt/earthquake_analysis directory
"""

import os
import pathlib

from cosmos import DbtDag, ExecutionConfig, ProfileConfig, ProjectConfig
from cosmos.profiles.bigquery import GoogleCloudOauthProfileMapping
from pendulum import datetime

DBT_PROJECT_PATH = pathlib.Path(__file__).parent / "dbt/earthquake_analysis"
DBT_EXECUTABLE_PATH = f"{os.environ['AIRFLOW_HOME']}/virtualvenv/dbt_venv/bin/dbt"
GCP_PROJECT_NAME = os.environ["GCP_PROJECT_NAME"]

profile_config = ProfileConfig(
    profile_name="earthquake_analysis",
    target_name="earthquake_analysis",
    profile_mapping=GoogleCloudOauthProfileMapping(
        conn_id="google_cloud_default",
        profile_args={
            "dataset": "earthquake",
            "project": GCP_PROJECT_NAME,
            "type": "bigquery",
        },
    ),
)

project_config = ProjectConfig(DBT_PROJECT_PATH)
execution_config = ExecutionConfig(dbt_executable_path=DBT_EXECUTABLE_PATH)

generate_summary_tables = DbtDag(
    project_config=project_config,
    profile_config=profile_config,
    execution_config=execution_config,
    # normal dag parameters
    schedule_interval="@weekly",
    start_date=datetime(2025, 1, 8),
    catchup=False,
    dag_id="generate_summary_tables",
)
