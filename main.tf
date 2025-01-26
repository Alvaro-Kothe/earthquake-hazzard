terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "6.8.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

resource "random_uuid" "uuid" {
  keepers = {
    bucket_prefix = var.bucket_prefix
  }
}

resource "google_storage_bucket" "gcs_bucket" {
  name          = "${var.bucket_prefix}-${random_uuid.uuid.result}"
  location      = "US"
  storage_class = "STANDARD"
  force_destroy = true

  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 30
    }
  }
}

resource "google_bigquery_dataset" "default" {
  dataset_id                      = "earthquake"
  default_partition_expiration_ms = 2592000000  # 30 days
  default_table_expiration_ms     = 31536000000 # 365 days
  location                        = var.location
  friendly_name                   = "Earthquakes"
  description                     = "Earthquakes across the world"
  max_time_travel_hours           = 96 # 4 days

  delete_contents_on_destroy = true
}

resource "google_bigquery_table" "default" {
  dataset_id          = google_bigquery_dataset.default.dataset_id
  table_id            = "earthquake"
  deletion_protection = false # set to "true" in production

  table_constraints {
    primary_key {
      columns = ["earthquake_id"]
    }

    foreign_keys {

      referenced_table {
        project_id = google_bigquery_table.country_lookup.project
        dataset_id = google_bigquery_table.country_lookup.dataset_id
        table_id   = google_bigquery_table.country_lookup.table_id
      }

      column_references {
        referenced_column  = "country_id"
        referencing_column = "country_id"
      }
    }
  }

  time_partitioning {
    type          = "DAY"
    field         = "time"
    expiration_ms = 2592000000 # 30 days
  }
  require_partition_filter = true

  clustering = ["country_id", "alert"]

  schema = file("bigquery/earthquakes_schema.json")
}

resource "google_bigquery_table" "country_lookup" {
  dataset_id          = google_bigquery_dataset.default.dataset_id
  table_id            = "countries"
  deletion_protection = false # set to "true" in production

  table_constraints {
    primary_key {
      columns = ["country_id"]
    }
  }

  schema = file("bigquery/countries_schema.json")
}

# TODO: See if there is a better way to integrate the key into airflow
resource "google_service_account" "airflow" {
  account_id   = "airflow"
  display_name = "Orchestrator Airflow"
}

resource "google_service_account_key" "airflow_key" {
  service_account_id = google_service_account.airflow.name
}

# Assign GCS write and delete permissions to the service account for the bucket
resource "google_storage_bucket_iam_member" "airflow" {
  bucket = google_storage_bucket.gcs_bucket.name
  role   = "roles/storage.objectAdmin" # Allows writing and deleting objects in the bucket
  member = "serviceAccount:${google_service_account.airflow.email}"
}

resource "google_bigquery_dataset_iam_member" "airflow" {
  dataset_id = google_bigquery_table.default.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.airflow.email}"
}
