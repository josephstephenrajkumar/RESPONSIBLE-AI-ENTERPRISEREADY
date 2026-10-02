include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/ecs-litellm-proxy"
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
      groq_api_key       = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
      litellm_master_key = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
    }
  }
}

dependency "aurora" {
  config_path = "../aurora-postgres"

  mock_outputs = {
    postgres_url = "postgresql://app_admin:MockPassword123!@mock.cluster.local:5432/responsible_ai"
  }
}

inputs = {
  project_name       = "responsible-ai"
  environment        = "dev"
  vpc_id             = dependency.network.outputs.vpc_id
  private_subnet_ids = dependency.network.outputs.private_subnet_ids

  config_file_path = "${get_repo_root()}/litellm/config.yaml"

  # Dev shares the application Aurora cluster (LiteLLM creates its own
  # LiteLLM_* tables). Give it a separate database or schema in prod.
  database_url = dependency.aurora.outputs.postgres_url

  master_key_secret_arn = dependency.secrets.outputs.secret_arns.litellm_master_key
  provider_secret_arns = {
    GROQ_API_KEY = dependency.secrets.outputs.secret_arns.groq_api_key
  }

  ingress_cidr_blocks = [dependency.network.outputs.vpc_cidr_block]
  desired_count       = 1
  cpu                 = 512
  memory              = 1024

  tags = {
    Module = "ecs-litellm-proxy"
  }
}
