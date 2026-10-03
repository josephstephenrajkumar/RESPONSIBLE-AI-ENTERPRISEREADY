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
      groq_api_key        = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
      guardrails_token    = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
      litellm_gateway_key = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
      litellm_master_key  = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
      activepieces_service_password = "arn:aws:secretsmanager:ap-southeast-1:767141477889:secret:mock"
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
    repository_url = "767141477889.dkr.ecr.ap-southeast-1.amazonaws.com/responsible-ai-dev-ai-gateway"
  }
}

dependency "litellm" {
  config_path = "../ecs-litellm-proxy"

  mock_outputs = {
    proxy_url = "http://mock-litellm.internal"
  }
}

dependency "engine" {
  config_path = "../ecs-activepieces"

  mock_outputs = {
    engine_url = "http://mock-activepieces.internal"
  }
}

dependency "engine_api" {
  config_path = "../api-gateway-workflows"

  mock_outputs = {
    api_endpoint = "https://mock-workflows.execute-api.ap-southeast-1.amazonaws.com"
  }
}

inputs = {
  project_name       = "responsible-ai"
  environment        = "dev"
  vpc_id             = dependency.network.outputs.vpc_id
  private_subnet_ids = dependency.network.outputs.private_subnet_ids

  database_url       = dependency.aurora.outputs.database_url
  ecr_repository_url = dependency.ecr.outputs.repository_url
  image_tag          = "1c6425c"

  # All model traffic goes through the LiteLLM proxy. The gateway task gets a
  # LiteLLM virtual key (generate it with /key/generate and store it in the
  # litellm_gateway_key secret); it never receives GROQ_API_KEY.
  llm_gateway_mode           = "proxy"
  litellm_proxy_url          = dependency.litellm.outputs.proxy_url
  litellm_api_key_secret_arn = dependency.secrets.outputs.secret_arns.litellm_gateway_key
  llm_default_model          = "openai/gpt-oss-120b"
  llm_judge_model            = "judge-fast"
  llm_allowed_models         = ""
  # Admin model catalogue: providers the proxy can call (Groq via key, Bedrock via
  # the proxy task role). Model management uses the LiteLLM master key in dev.
  enabled_providers            = ["groq", "bedrock"]
  litellm_admin_key_secret_arn = dependency.secrets.outputs.secret_arns.litellm_master_key
  finops_monthly_budget_usd  = 50

  guardrails_token_secret_arn = ""

  # Workflow Apps: the gateway owns the Activepieces control plane. Internal ALB for
  # API calls, HTTP API endpoint for the embedded builder and chat, service password in
  # Secrets Manager. The piece archives ship inside the gateway image (/app/pieces).
  activepieces_enabled                     = true
  activepieces_api_url                     = dependency.engine.outputs.engine_url
  activepieces_public_url                  = dependency.engine_api.outputs.api_endpoint
  activepieces_service_password_secret_arn = dependency.secrets.outputs.secret_arns.activepieces_service_password
  activepieces_litellm_url                 = dependency.litellm.outputs.proxy_url
  workflow_default_budget_usd              = 5
  workflow_platform_budget_usd             = 10
  observability_console_url   = "https://ap-southeast-1.console.aws.amazon.com/xray/home?region=ap-southeast-1#/traces"

  cognito_region        = "ap-southeast-1"
  cognito_user_pool_id  = dependency.cognito.outputs.user_pool_id
  cognito_app_client_id = dependency.cognito.outputs.app_client_id
  cognito_domain        = dependency.cognito.outputs.hosted_ui_domain
  cognito_issuer        = dependency.cognito.outputs.issuer

  frontend_origins = "http://localhost:5173,http://localhost:3000,https://d12wylhj234wu3.cloudfront.net"
  auth_required    = true
  desired_count    = 1
  cpu              = 1024
  memory           = 2048

  tags = {
    Module = "ecs-ai-gateway"
  }
}
