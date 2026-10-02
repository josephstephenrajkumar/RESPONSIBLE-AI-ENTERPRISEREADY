include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "../../../modules/cognito"
}

inputs = {
  project_name = "responsible-ai"
  environment  = "dev"

  # User pool configuration
  user_pool_name = "responsible-ai-dev"

  # Password policy
  password_minimum_length    = 12
  password_require_uppercase = true
  password_require_lowercase = true
  password_require_numbers   = true
  password_require_symbols   = true

  # MFA
  mfa_configuration = "OPTIONAL"

  # Email configuration
  email_sending_account = "COGNITO_DEFAULT"

  # App client configuration
  app_client_name = "responsible-ai-app-dev"
  allow_admin_user_password_auth = true
  domain_prefix   = "responsible-ai-dev-767141477889"
  callback_urls = [
    "http://localhost:5173",
    "http://localhost:5173/",
    "http://localhost:3000",
    "http://localhost:3000/",
    "https://d12wylhj234wu3.cloudfront.net",
    "https://d12wylhj234wu3.cloudfront.net/",
  ]
  logout_urls = [
    "http://localhost:5173",
    "http://localhost:5173/",
    "http://localhost:3000",
    "http://localhost:3000/",
    "https://d12wylhj234wu3.cloudfront.net",
    "https://d12wylhj234wu3.cloudfront.net/",
  ]

  allowed_oauth_scopes = ["email", "openid", "profile"]
  allowed_oauth_flows  = ["code"]
  allow_signup         = true

  tags = {
    Module = "cognito"
  }
}
