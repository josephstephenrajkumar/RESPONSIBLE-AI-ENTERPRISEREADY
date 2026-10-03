include "root" {
  path = find_in_parent_folders()
}

# Public HTTPS entry for the Activepieces engine (builder + chat UI + its API) at the
# root of its own execute-api domain. The engine sets its own CORS headers, so the
# API Gateway CORS configuration is disabled here.
terraform {
  source = "../../../modules/api-gateway"
}

dependency "network" {
  config_path = "../network"

  mock_outputs = {
    private_subnet_ids = ["subnet-00000000000000001", "subnet-00000000000000002"]
  }
}

dependency "engine" {
  config_path = "../ecs-activepieces"

  mock_outputs = {
    alb_listener_arn = "arn:aws:elasticloadbalancing:ap-southeast-1:767141477889:listener/app/mock/123/456"
  }
}

inputs = {
  project_name       = "responsible-ai"
  environment        = "dev"
  name_suffix        = "-workflows"
  enable_cors        = false
  private_subnet_ids = dependency.network.outputs.private_subnet_ids
  alb_listener_arn   = dependency.engine.outputs.alb_listener_arn
  allowed_origins    = []

  tags = {
    Module = "api-gateway-workflows"
  }
}
