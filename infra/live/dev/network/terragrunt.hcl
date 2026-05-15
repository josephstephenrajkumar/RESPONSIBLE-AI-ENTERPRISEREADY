include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/network"
}

inputs = {
  project_name = "responsible-ai"
  environment  = "dev"

  # VPC Configuration
  vpc_cidr = "10.0.0.0/16"

  # Public subnets for API Gateway and CloudFront
  public_subnet_cidrs = [
    "10.0.1.0/24",
    "10.0.2.0/24"
  ]

  # Private subnets for ECS and Aurora
  private_subnet_cidrs = [
    "10.0.10.0/24",
    "10.0.11.0/24"
  ]

  # Database subnets for Aurora
  database_subnet_cidrs = [
    "10.0.20.0/24",
    "10.0.21.0/24"
  ]

  enable_nat_gateway = true
  enable_vpn_gateway = false

  tags = {
    Module = "network"
  }
}
