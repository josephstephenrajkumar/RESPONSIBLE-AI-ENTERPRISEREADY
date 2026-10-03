include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/ecs-activepieces"
}

dependency "network" {
  config_path = "../network"

  mock_outputs = {
    vpc_id             = "vpc-00000000000000000"
    vpc_cidr_block     = "10.0.0.0/16"
    private_subnet_ids = ["subnet-00000000000000001", "subnet-00000000000000002"]
  }
}

dependency "secrets" {
  config_path = "../secrets"

  mock_outputs = {
    secret_arns = {
      activepieces_encryption_key = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
      activepieces_jwt_secret     = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
      database_master_password    = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
    }
  }
}

dependency "aurora" {
  config_path = "../aurora-postgres"

  mock_outputs = {
    cluster_endpoint = "mock.cluster.local"
    database_name    = "responsible_ai"
  }
}

inputs = {
  project_name       = "responsible-ai"
  environment        = "dev"
  vpc_id             = dependency.network.outputs.vpc_id
  private_subnet_ids = dependency.network.outputs.private_subnet_ids

  image = "activepieces/activepieces:0.92.0"

  # Dev shares the application Aurora database (TD-13, TD-32): the engine creates
  # its own tables. Give it its own database and Redis in prod.
  postgres_host                = dependency.aurora.outputs.cluster_endpoint
  postgres_database            = dependency.aurora.outputs.database_name
  postgres_username            = "app_admin"
  postgres_password_secret_arn = dependency.secrets.outputs.secret_arns.database_master_password

  encryption_key_secret_arn = dependency.secrets.outputs.secret_arns.activepieces_encryption_key
  jwt_secret_secret_arn     = dependency.secrets.outputs.secret_arns.activepieces_jwt_secret

  ingress_cidr_blocks = [dependency.network.outputs.vpc_cidr_block]
  desired_count       = 1
  cpu                 = 2048
  memory              = 4096

  tags = {
    Module = "ecs-activepieces"
  }
}
