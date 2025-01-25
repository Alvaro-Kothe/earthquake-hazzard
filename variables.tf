variable "project" {
  default = "my-project"
}

variable "region" {
  default = "us-central1"
}

variable "bucket_prefix" {
  type    = string
  default = "earthquake-data"
}
