variable "region" { default = "us-east-1" }
variable "environment" {
  type = string
  validation {
    condition     = contains(["development", "staging", "production"], var.environment)
    error_message = "Environment must be development, staging or production."
  }
}
variable "vpc_cidr" { default = "10.42.0.0/16" }
variable "certificate_arn" {
  type        = string
  description = "Existing ACM certificate in this region for app_domain."
}
variable "app_domain" {
  type        = string
  description = "Public hostname; point an external DNS alias at alb_dns_name."
}
variable "oidc_issuer" { type = string }
variable "oidc_client_id" { default = "enterpriseflow-web" }
variable "oidc_audience" { default = "enterpriseflow-api" }
variable "api_image" {
  type        = string
  description = "Immutable ECR image URI including digest or release SHA tag."
}
variable "web_image" { type = string }
variable "desired_count" {
  default     = 0
  description = "Keep zero for initial infrastructure bootstrap. Populate secrets and migrate before setting to 1 (2 in production)."
  validation {
    condition     = var.desired_count >= 0 && var.desired_count <= 10
    error_message = "Desired count must be between zero and ten."
  }
}
variable "database_instance_class" { default = "db.t4g.small" }
variable "redis_node_type" { default = "cache.t4g.small" }
variable "redis_auth_token" {
  type        = string
  sensitive   = true
  description = "32+ alphanumeric characters supplied through TF_VAR_redis_auth_token; also set in runtime REDIS_URL. This value is present in encrypted Terraform state."
  validation {
    condition     = can(regex("^[A-Za-z0-9]{32,128}$", var.redis_auth_token))
    error_message = "Use 32–128 alphanumeric characters."
  }
}
variable "github_repository" { default = "SreytouchLang/Enterprise-FlowAI-Secure-Enterprise-Agent-Workflow-Automation-Platform" }
variable "github_oidc_provider_arn" {
  type        = string
  description = "Existing IAM OIDC provider for https://token.actions.githubusercontent.com. One per AWS account."
}
variable "enable_deletion_protection" { default = true }
variable "log_retention_days" { default = 30 }

variable "clamav_host" {
  type        = string
  description = "Private ClamAV daemon DNS; run a maintained signature-updating scanner in the VPC. Required for production ingestion."
}
