# Earthquake Hazards Dashboard

This project implements a data pipeline using the [USGS Earthquake API](https://www.usgs.gov/programs/earthquake-hazards) to
ingest, process, and visualize global earthquake data in a dashboard.

## Dashboard Components

<!-- TODO: Add images or a GIF demonstrating the dashboard's interactivity -->

The dashboard consists of three primary visualization components:

- **Earthquake Map**: Displays the geographical locations where earthquakes occurred.
- **Time Series Plots**: Two separate plots showing the average earthquake magnitude by country and continent over time.
  - **NOTE:** Since the data for this plots is aggregated by continent and country,
    the average magnitude for the $i$th continent is defined as the average of the average of the earthquake magnitude weighted by the number of earthquakes:
    $$\frac{\sum_{j=1}^{n_i} \bar x_{ij} m_{ij}}{\sum_{j=1}^{n_i} m_{ij}},$$
    where $n_{i}$ is the number of countries,
    $\bar x_{ij}$ is the average magnitude for the $j$th country in the $i$th continent
    and $m_{ij}$ is the number of earthquakes.
- **Pie Charts**: Visualizes the distribution of earthquakes by magnitude category, country, and continent.

## Data Sources

- **Earthquake Data**: Obtained from the [USGS Earthquake Hazards API](https://www.usgs.gov/programs/earthquake-hazards).
- **Geolocation Data**: Countries and continents are assigned using reverse geolocation from the [Nominatim API](https://nominatim.openstreetmap.org/ui/search.html).

## Observations

- Due to the data source, there is a notable concentration of recorded earthquakes in the United States and nearby regions.
- Continents were identified based on the country information retrieved. If the Nominatim API failed to resolve a country, the corresponding continent was left unassigned.

## Table Structure

The schema for the earthquake data is defined in [`earthquakes_schema.json`](/bigquery/earthquakes_schema.json).
The table is partitioned daily and clustered by `earthquake_id`, `continent` and `country`, as specified in [`main.tf`](/main.tf).

The daily partition on the earthquake events helps building the incremental table for the time series plots.
The cluster on the `earthquake_id` improves query performance to update the `country` and `continent`.
Finally, clustering by `country` and `continent` improves query performance for aggregation queries used for the dashboard.

## Data Pipeline

![earthquake-hazard-pipeline drawio](https://github.com/user-attachments/assets/59541657-ae36-414d-9a06-89e5dcfee9fa)

The pipeline runs daily on a Google Cloud Compute instance with Fedora CoreOS.
The instance starts at **00:00 UTC** and shuts down at **01:45 UTC**.
While active, a systemd service defined in [`cloud-startup`](/cloud-startup/docker-compose.bu) starts the required containers and workflows.

The workflows, implemented as Apache Airflow DAGs, are located in the [`src/dags`](/src/dags) directory. The main DAGs are:

1. **[`get_earthquake_data.py`](/src/dags/get_earthquake_data.py) (ELT - Extract, Load, Transform)**:
   - Fetches data from the USGS API.
   - Stores the `geojson` raw data in a Google Cloud Storage data lake.
   - Processes and loads cleaned data into BigQuery.
2. **[`get_country_info.py`](/src/dags/get_country_info.py) (Enhancement)**:
   - Uses the Nominatim API to determine the country of each earthquake event.
3. **[`generate_summary_tables.py`](/src/dags/generate_summary_tables.py) (Transform & Aggregate)**:
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
docker-compose -f docker-compose.yaml -f docker-compose-dev.yaml up
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
- **[Nominatim API](https://nominatim.openstreetmap.org/ui/search.html)**: Reverse geocoding for country lookup.
- **[Terraform](https://www.terraform.io/)**: Infrastructure as code.
- **[USGS Earthquake API](https://earthquake.usgs.gov)**: Earthquake data source.
- **[dbt](https://docs.getdbt.com/)**: Data transformation.

The continent lookup was sourced from [this dataset](https://gist.github.com/stevewithington/20a69c0b6d2ff846ea5d35e5fc47f26c) and converted into [`country_to_continent.json`](/src/dags/include/country_to_continent.json).

## TODO

- [x] Use Terraform/OpenTofu to provision a cloud VM.
- [x] Choose a cloud provider (GCP, Azure, AWS).
- [x] Select a dataset/data stream API.
- [x] Set up an orchestrator for the ETL pipeline.
  - [x] Run the orchestrator in the cloud.
  - [x] Load data into a data warehouse.
- [x] Perform transformations on the data (dbt or Spark).
- [x] Integrate dbt into the workflow.
- [x] Build a dashboard from the transformed data.
- [ ] Deploy the pipeline on Kubernetes in the cloud.
