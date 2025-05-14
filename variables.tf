variable "domain_name" {
  type        = string
  description = "Primary domain name."
}

variable "domain_prefix" {
  type        = string
  description = "Domain prefix."
  default     = "terraform-state"
}

variable "hosted_zone_id" {
  description = "Route53 Hosted Zone ID."
}

variable "tf_backend_username" {
  description = "Terraform backend basic auth username."
}

variable "tf_backend_password" {
  description = "Terraform backend basic auth password."
}
