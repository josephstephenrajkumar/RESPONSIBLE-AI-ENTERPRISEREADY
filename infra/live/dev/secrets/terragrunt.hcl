include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/secrets"
}

dependency "network" {
  config_path = "../network"

  mock_outputs = {
    vpc_id = "vpc-00000000000000000"
  }
}

inputs = {
  project_name = "responsible-ai"
  environment  = "dev"
  vpc_id       = dependency.network.outputs.vpc_id

  # Secrets to store
  secrets = {
    groq_api_key = {
      description = "Groq API key for LLM calls"
    }

    database_master_password = {
      description = "Aurora PostgreSQL master password"
    }

    jwt_secret = {
      description = "JWT signing secret for Cognito"
    }
  }

  tags = {
    Module = "secrets"
  }
}
