terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
  # Supply bucket/key/region with terraform init -backend-config=... .
  # State bucket must exist, be private, versioned and encrypted.
  backend "s3" { use_lockfile = true }
}
provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "EnterpriseFlowAI", Environment = var.environment, ManagedBy = "Terraform" }
  }
}
data "aws_availability_zones" "available" { state = "available" }
data "aws_caller_identity" "current" {}
locals {
  name = "enterpriseflow-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}