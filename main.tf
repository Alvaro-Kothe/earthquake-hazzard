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

data "google_project" "default" {}

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
  dataset_id            = "earthquake"
  location              = var.location
  friendly_name         = "Earthquakes"
  description           = "Earthquakes across the world"
  max_time_travel_hours = 96 # 4 days

  delete_contents_on_destroy = true
}

resource "google_bigquery_table" "default" {
  dataset_id          = google_bigquery_dataset.default.dataset_id
  table_id            = "earthquake"
  deletion_protection = true # set to "true" in production

  time_partitioning {
    type  = "DAY"
    field = "time"
  }

  # NOTE: clustering columns with high cardinality is good
  # https://cloud.google.com/bigquery/docs/clustered-tables#when_to_use_clustering
  clustering = ["earthquake_id", "continent", "country"]

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

resource "google_project_iam_member" "vm_schedule" {
  project = data.google_project.default.project_id
  role    = "roles/compute.instanceAdmin.v1"
  member  = "serviceAccount:service-${data.google_project.default.number}@compute-system.iam.gserviceaccount.com"
}

# Create a Google Cloud VM instance
resource "google_compute_instance" "default" {
  name         = var.vm_name
  machine_type = "e2-standard-2"
  zone         = var.zone

  boot_disk {
    initialize_params {
      image = "fedora-coreos-cloud/fedora-coreos-stable"
      size  = 20
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

  metadata = {
    user-data = file("./cloud-startup/docker-compose.ign")
  }

  resource_policies = [google_compute_resource_policy.hourly.id]

  depends_on = [google_project_iam_member.vm_schedule]

  lifecycle {
    # HACK: prevents asking to update the instance without changes.
    # https://stackoverflow.com/a/68945937
    ignore_changes = [boot_disk]
  }
}

resource "google_compute_resource_policy" "hourly" {
  name        = "gce-policy"
  region      = var.region
  description = "Start and stop instances"
  instance_schedule_policy {
    time_zone = "Etc/UTC"

    # Start vm at midnight and keep it running for 1h and 15m
    vm_start_schedule {
      schedule = "0 0 * * *"
    }

    vm_stop_schedule {
      schedule = "0 1 * * *"
    }
  }
}
