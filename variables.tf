variable "project" {
  type        = string
  default     = "my-project"
  description = "Project name"
}

variable "location" {
  type        = string
  default     = "US"
  description = "Location"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Project region"
}

variable "bucket_prefix" {
  type        = string
  default     = "earthquake-data"
  description = "Bucket prefix"
}

