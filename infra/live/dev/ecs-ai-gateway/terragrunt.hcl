include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/ecs-ai-gateway"
}

dependency "network" {
  config_path = "../network"

  mock_outputs = {
    vpc_id             = "vpc-00000000000000000"
    private_subnet_ids = ["subnet-00000000000000001", "subnet-00000000000000002"]
  }
}

dependency "secrets" {
  config_path = "../secrets"

  mock_outputs = {
    secret_arns = {
      groq_api_key      = "arn:aws:secretsmanager:ap-southeast-1:311464491957:secret:mock"
      guardrails_token = "arn:aws:secretsmanager:ap-southeast-1:311464491957:secret:mock"
    }
  }
}

dependency "cognito" {
  config_path = "../cognito"

  mock_outputs = {
    user_pool_id  = "ap-southeast-1_mock"
    app_client_id = "mockclientid"
    hosted_ui_domain = "https://mock.auth.ap-southeast-1.amazoncognito.com"
    issuer        = "https://cognito-idp.ap-southeast-1.amazonaws.com/ap-southeast-1_mock"
  }
}

dependency "aurora" {
  config_path = "../aurora-postgres"

  mock_outputs = {
    database_url = "postgresql+psycopg2://app_admin:MockPassword123!@mock.cluster.local:5432/responsible_ai"
  }
}

dependency "ecr" {
  config_path = "../ecr"

  mock_outputs = {
    repository_url = "311464491957.dkr.ecr.ap-southeast-1.amazonaws.com/responsible-ai-dev-ai-gateway"
  }
}

inputs = {
  project_name       = "responsible-ai"
  environment        = "dev"
  vpc_id             = dependency.network.outputs.vpc_id
  private_subnet_ids = dependency.network.outputs.private_subnet_ids

  database_url       = dependency.aurora.outputs.database_url
  ecr_repository_url = dependency.ecr.outputs.repository_url
  image_tag          = "latest"

  groq_api_key_secret_arn     = dependency.secrets.outputs.secret_arns.groq_api_key
  guardrails_token_secret_arn = "arn:aws:secretsmanager:ap-southeast-1:311464491957:secret:responsible-ai-dev/guardrails_token-QbWaDj"
  groq_model                  = "llama-3.3-70b-versatile"
  groq_api_url                = "https://api.groq.com/openai/v1"
  observability_console_url   = "https://ap-southeast-1.console.aws.amazon.com/xray/home?region=ap-southeast-1#/traces"

  cognito_region        = "ap-southeast-1"
  cognito_user_pool_id  = dependency.cognito.outputs.user_pool_id
  cognito_app_client_id = dependency.cognito.outputs.app_client_id
  cognito_domain        = dependency.cognito.outputs.hosted_ui_domain
  cognito_issuer        = dependency.cognito.outputs.issuer

  frontend_origins = "http://localhost:5173,http://localhost:3000,https://df22y6w4tmruy.cloudfront.net"
  auth_required    = true
  desired_count    = 1
  cpu              = 1024
  memory           = 2048

  tags = {
    Module = "ecs-ai-gateway"
  }
}
