# Earthquake Hazards Dashboard

This project creates a pipeline using the [USGS earthquake api](https://www.usgs.gov/programs/earthquake-hazards) to deliver it's data to the Cloud to create a Dashboard to visualize the earthquake data across the world.

## TODO

- [ ] Use terraform/opentofu to setup a vm on the cloud
- [ ] Choose a cloud provider: GCP, Azure, AWS
- [ ] Choose a dataset / datastream api
- [ ] Setup an orchestrator for an ETL pipeline
    - [ ] The orchestrator needs to run on the cloud
    - [ ] The orchestrator needs to move the data to a data warehouse
- [ ] Perform transformations on the data (use dbt or spark)
- [ ] Use the transformed data to create a dashboard.
