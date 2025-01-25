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

# TODO: See if there is a better way to integrate the key into airflow
resource "google_service_account" "airflow_gcs" {
  account_id   = "airflow-gcs"
  display_name = "Airflow earthquake data downloader"
}

# Assign GCS write and delete permissions to the service account for the bucket
resource "google_storage_bucket_iam_member" "bucket_permissions" {
  bucket = google_storage_bucket.gcs_bucket.name
  role   = "roles/storage.objectAdmin" # Allows writing and deleting objects in the bucket
  member = "serviceAccount:${google_service_account.airflow_gcs.email}"
}

resource "google_service_account_key" "airflow_gcs_key" {
  service_account_id = google_service_account.airflow_gcs.name
}
