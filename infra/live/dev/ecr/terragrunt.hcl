include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/ecr"
}

inputs = {
  project_name    = "responsible-ai"
  environment     = "dev"
  repository_name = "responsible-ai-dev-ai-gateway"

  tags = {
    Module = "ecr"
  }
}
