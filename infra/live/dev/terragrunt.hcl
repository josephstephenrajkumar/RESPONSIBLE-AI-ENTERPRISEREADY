locals {
  project_name    = "responsible-ai"
  environment     = "dev"
  aws_account_id  = "311464491957"
  aws_region      = "ap-southeast-1"
  resource_prefix = "${local.project_name}-${local.environment}"
  state_bucket    = "${local.project_name}-terraform-state-${local.environment}-${local.aws_account_id}"
  lock_table      = "${local.project_name}-terraform-locks-${local.environment}"
}

remote_state {
  backend = "s3"

  generate = {
    path      = "backend.tf"
    if_exists = "overwrite_terragrunt"
  }

  config = {
    bucket         = local.state_bucket
    key            = "${path_relative_to_include()}/terraform.tfstate"
    region         = local.aws_region
    encrypt        = true
    dynamodb_table = local.lock_table
  }
}

generate "provider" {
  path      = "provider.tf"
  if_exists = "overwrite_terragrunt"
  contents  = <<EOF
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = "${local.aws_region}"

  default_tags {
    tags = {
      Project     = "${local.project_name}"
      Environment = "${local.environment}"
      ManagedBy   = "terraform"
    }
  }
}
EOF
}
