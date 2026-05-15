include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/frontend-s3-cloudfront"
}

dependency "api" {
  config_path = "../api-gateway"

  mock_outputs = {
    api_endpoint = "https://mock.execute-api.ap-southeast-1.amazonaws.com"
  }
}

inputs = {
  project_name = "responsible-ai"
  environment  = "dev"
  api_endpoint = dependency.api.outputs.api_endpoint

  tags = {
    Module = "frontend-s3-cloudfront"
  }
}
