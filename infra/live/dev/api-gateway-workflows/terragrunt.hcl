include "root" {
  path = find_in_parent_folders()
}

# LEGACY (first Workflow Apps delivery, 2026-10-03): public HTTPS entry for the Activepieces
# engine UI. Nothing references it since the Workflow Studio (Sprint WS-3); the gateway is the
# engine's only client. Scheduled for removal: run `terragrunt destroy` here, then delete this
# folder. Kept only so the destroy can be run from the committed configuration.
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
