output "bucket_name" {
  value = google_storage_bucket.gcs_bucket.name
}

output "airflow_gcs_key" {
  value     = google_service_account_key.airflow_key.private_key
  sensitive = true
}
