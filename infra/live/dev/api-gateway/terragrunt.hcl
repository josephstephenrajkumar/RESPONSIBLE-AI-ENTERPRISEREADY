include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/api-gateway"
}

dependency "network" {
  config_path = "../network"

  mock_outputs = {
    private_subnet_ids = ["subnet-00000000000000001", "subnet-00000000000000002"]
  }
}

dependency "ecs" {
  config_path = "../ecs-ai-gateway"

  mock_outputs = {
    alb_listener_arn = "arn:aws:elasticloadbalancing:ap-southeast-1:311464491957:listener/app/mock/123/456"
  }
}

inputs = {
  project_name       = "responsible-ai"
  environment        = "dev"
  private_subnet_ids = dependency.network.outputs.private_subnet_ids
  alb_listener_arn   = dependency.ecs.outputs.alb_listener_arn
  allowed_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://df22y6w4tmruy.cloudfront.net"
  ]

  tags = {
    Module = "api-gateway"
  }
}
