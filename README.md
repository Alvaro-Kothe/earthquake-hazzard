# Earthquake Hazards Dashboard

This project implements a data pipeline using the [USGS Earthquake API](https://www.usgs.gov/programs/earthquake-hazards) to
ingest, process, and visualize global earthquake data in a dashboard.

The dashboard aids to visualize where the earthquakes occurs around the globe,
countries and continents with the most severe earthquakes,
and how the earthquakes magnitudes changes over time.

## Dashboard Components

<https://github.com/user-attachments/assets/63471a51-158f-4068-8b09-648a2a78d7ee>

The dashboard consists of four primary visualization components:

- **Pie Charts**: Visualizes the distribution of earthquakes by magnitude category, country, and continent.
- **Earthquake Map**: Displays the geographical locations where earthquakes occurred.
- **Time Series Plot**: Shows the average earthquake magnitude by continent over time.
    - **NOTE:** Since the data for this plots is aggregated by continent and country,
      the average magnitude for the $i$-th continent is defined as the average of the average of the earthquake magnitude weighted by the number of earthquakes:
      $$\frac{\sum_{j=1}^{n_i} \bar x_{ij} m_{ij}}{\sum_{j=1}^{n_i} m_{ij}},$$
      where $n_{i}$ is the number of countries,
      $\bar x_{ij}$ is the average magnitude for the $j$-th country in the $i$-th continent
      and $m_{ij}$ is the number of earthquakes.
- **Bar Plot:** Average earthquakes magnitudes by country.

## Data Sources

- **Earthquake Data**: Obtained from the [USGS Earthquake Hazards API](https://www.usgs.gov/programs/earthquake-hazards).
- **Geolocation Data**: Countries and continents are assigned using reverse geolocation with [natural earth](https://www.naturalearthdata.com/) shapefiles.

## Observations

- Due to the data source, there is a notable concentration of recorded earthquakes in the United States and nearby regions.
- USGS is capable of detecting very small earthquakes in the USA region, which distort the magnitude downwards for the country USA and continent North America,
  which ends up differing greatly from other regions.

## Table Structure

The schema for the earthquake data is defined in [`earthquakes_schema.json`](/bigquery/earthquakes_schema.json).
The table is partitioned daily and clustered by `earthquake_id`, `continent` and `country`, as specified in [`main.tf`](/main.tf).

The daily partition on the earthquake events helps building the incremental table for the time series plots.
The cluster on the `earthquake_id` improves query performance to insert new rows.
Finally, clustering by `country` and `continent` improves query performance for aggregation queries used for the dashboard.

## Data Pipeline

![earthquake-hazard-pipeline drawio](https://github.com/user-attachments/assets/9cdf7ad1-7c30-4b73-85b3-f70c74642670)

The pipeline runs daily on a Google Cloud Compute instance with Fedora CoreOS.
The instance starts at **00:00 UTC** and shuts down at **01:00 UTC**.
While active, a systemd service defined in [`cloud-startup`](/cloud-startup/docker-compose.bu) starts the required containers and workflows.

The workflows, implemented as Apache Airflow DAGs, are located in the [`src/dags`](/src/dags) directory. The main DAGs are:

1. **[`get_earthquake_data.py`](/src/dags/get_earthquake_data.py) (ELT - Extract, Load, Transform)**:
    - Fetches data from the USGS API.
    - Stores the `geojson` raw data in a Google Cloud Storage data lake.
    - Processes and loads cleaned data into BigQuery.
2. **[`generate_summary_tables.py`](/src/dags/generate_summary_tables.py) (Transform & Aggregate)**:
    - Uses `dbt` to generate precomputed summary statistics for dashboard visualization.
    - The transformation logic is implemented in [`earthquake_analysis`](/src/dags/dbt/earthquake_analysis).

## Local Environment Setup

### Cloud Infrastructure Setup

The cloud environment is provisioned using Terraform.
Start by creating an `.env` file from the example:

```sh
cp .env.example .env
```

Then, initialize and apply the Terraform configuration:

```sh
terraform init
terraform plan
terraform apply
```

Next, update the `.env` file with the generated cloud information.
Retrieve the Airflow service account key with:

```sh
terraform output -raw airflow_gcs_key | base64 -d > /path/to/your/private/key.json
```

Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable in `.env` to the key file path.

### Compute Instance Configuration

Follow the instructions in [`cloud-setup.md`](/docs/cloud-setup.md) to configure the VM.

### Running the Airflow Service

The project includes two `docker-compose` files:

- **`docker-compose.yaml`**: Used for the compute engine.
- **`docker-compose-dev.yaml`**: Adds local secrets for development.

To start Airflow in production:

```sh
docker compose up
```

To start Airflow in development:

```sh
docker compose -f docker-compose.yaml -f docker-compose-dev.yaml up
```

Ensure environment variables are correctly configured and credentials are provided in both environments.

### Apache Superset Setup

Clone the Superset repository:

```sh
git submodule update --init --recursive
```

Start Superset:

```sh
docker compose -f ./superset/docker-compose-image-tag.yml up
```

To create the dashboard:

1. [Connect Superset to BigQuery](https://superset.apache.org/docs/configuration/databases/#google-bigquery).
2. Add the dataset to Superset.
3. Enable maps by setting your [MAPBOX_API_KEY](https://superset.apache.org/docs/faq/#why-is-the-map-not-visible-in-the-geospatial-visualization).

## Tools & Technologies

- **[Apache Airflow](https://airflow.apache.org/)**: Workflow orchestration.
- **[Apache Superset](https://superset.apache.org/)**: Business Intelligence & data visualization.
- **[Docker](https://www.docker.com/)**: Containerization.
- **[Fedora CoreOS](https://fedoraproject.org/coreos/)**: Cloud-optimized OS.
- **[Google Cloud Platform](https://cloud.google.com/)**: Cloud services.
- **[Mapbox](https://www.mapbox.com/)**: Geospatial visualization.
- **[Terraform](https://www.terraform.io/)**: Infrastructure as code.
- **[USGS Earthquake API](https://earthquake.usgs.gov)**: Earthquake data source.
- **[dbt](https://docs.getdbt.com/)**: Data transformation.
