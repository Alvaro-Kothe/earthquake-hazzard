# Earthquake Hazards Dashboard

This project creates a pipeline using the [USGS earthquake api](https://www.usgs.gov/programs/earthquake-hazards) to deliver it's data to the Cloud to create a Dashboard to visualize the earthquake data across the world.

## Table Streucture

The table schema with the earthquake information is defined in [`earthquakes.json`](/bigquery/earthquakes_schema.json).
This table is partitioned daily and clustered by country and alert, defined in [`main.tf`](/main.tf).

## Setup Environment

### Setup the cloud

You can configure the environment for the cloud through terraform and environment variables.
Firstly, create the `.env` file from `.env.example`:

```
cp .env.example .env
```

Then, setup the cloud with terraform:

```
terraform init
terraform plan
terraform apply
```

Finally, fill the `.env` file with the correct values.
The cloud information you get from terraform using `terraform output`.
The key to be used for airflow you get with this command:

```
terraform output -raw airflow_gcs_key | base64 -d
```

To configure the VM look at [cloud-setup.md](/docs/cloud-setup.md).

### Run the Airflow service

There are two `docker-compose` files.
The first has the secret blocks omitted to use the Google cloud's provided secrets.
The second simply add the secrets for local development.

In the production environment, start the services with

```
docker compose up
```

In the development environment starts it with

```
docker-compose -f docker-compose.yaml -f docker-compose.dev.yaml up
```

Be sure to setup the correct environment variables.
Also, be sure to provide the path for your credentials, or from the service.

## Used Tools

- [Earthquake Hazards Program API](https://earthquake.usgs.gov): Earthquake information across the world.
- [Nominatim API](https://nominatim.openstreetmap.org/ui/search.html): Reverse Geocoding
- [Superset](https://superset.apache.org/): BI
- [mapbox](https://www.mapbox.com/): map

The continent lookup was taken from <https://gist.github.com/stevewithington/20a69c0b6d2ff846ea5d35e5fc47f26c>.

## TODO

- [x] Use terraform/opentofu to setup a vm on the cloud
- [x] Choose a cloud provider: GCP, Azure, AWS
- [x] Choose a dataset / datastream api
- [ ] Setup an orchestrator for an ETL pipeline
  - [ ] The orchestrator needs to run on the cloud
  - [x] The orchestrator needs to move the data to a data warehouse
- [ ] Perform transformations on the data (use dbt or spark)
- [ ] Use the transformed data to create a dashboard.
