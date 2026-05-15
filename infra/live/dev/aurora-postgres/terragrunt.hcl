include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/aurora-postgres"
}

dependency "network" {
  config_path = "../network"

  mock_outputs = {
    vpc_id              = "vpc-00000000000000000"
    vpc_cidr_block      = "10.0.0.0/16"
    database_subnet_ids = ["subnet-00000000000000001", "subnet-00000000000000002"]
  }
}

dependency "secrets" {
  config_path = "../secrets"

  mock_outputs = {
    database_master_password = "MockPassword123!"
  }
}

inputs = {
  project_name        = "responsible-ai"
  environment         = "dev"
  vpc_id              = dependency.network.outputs.vpc_id
  allowed_cidr_blocks = [dependency.network.outputs.vpc_cidr_block]
  database_subnet_ids = dependency.network.outputs.database_subnet_ids

  db_name         = "responsible_ai"
  master_username = "app_admin"
  master_password = dependency.secrets.outputs.database_master_password
  min_capacity    = 0.5
  max_capacity    = 2

  tags = {
    Module = "aurora-postgres"
  }
}
