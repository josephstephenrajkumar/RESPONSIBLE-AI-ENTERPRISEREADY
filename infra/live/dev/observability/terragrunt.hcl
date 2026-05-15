include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/observability"
}

dependency "ecs" {
  config_path = "../ecs-ai-gateway"

  mock_outputs = {
    cluster_name   = "responsible-ai-dev-cluster"
    service_name   = "responsible-ai-dev-ai-gateway"
    log_group_name = "/ecs/responsible-ai-dev-ai-gateway"
  }
}

inputs = {
  project_name     = "responsible-ai"
  environment      = "dev"
  ecs_cluster_name = dependency.ecs.outputs.cluster_name
  ecs_service_name = dependency.ecs.outputs.service_name
  log_group_name   = dependency.ecs.outputs.log_group_name

  tags = {
    Module = "observability"
  }
}
