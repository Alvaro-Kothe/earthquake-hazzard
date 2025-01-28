terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.8"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

resource "random_uuid" "bucket_suffix" {
  keepers = {
    bucket_prefix = var.bucket_prefix
  }
}

resource "google_storage_bucket" "gcs_bucket" {
  name          = "${var.bucket_prefix}-${random_uuid.bucket_suffix.result}"
  location      = var.location
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

  time_partitioning {
    type          = "DAY"
    field         = "time"
    expiration_ms = 2592000000 # 30 days
  }

  clustering = ["continent", "country", "alert"]

  schema = file("bigquery/earthquakes_schema.json")
}

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

resource "google_project_iam_member" "bigquery_job_user" {
  project = google_bigquery_table.default.project
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.airflow.email}"
}

# Create a Google Cloud VM instance
resource "google_compute_instance" "default" {
  name         = var.vm_name
  machine_type = "e2-standard-4"
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "family/debian-12"
      size  = 30
    }
  }

  network_interface {
    network = "default"
    access_config {}
  }

  service_account {
    email  = google_service_account.airflow.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
}

# TODO: Create metadata database for AIRFLOW
# TODO: start docker compose service
# TODO: Schedule VM to start and shutdown: https://cloud.google.com/compute/docs/instances/schedule-instance-start-stop
