variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "user_pool_name" {
  type = string
}

variable "password_minimum_length" {
  type = number
}

variable "password_require_uppercase" {
  type = bool
}

variable "password_require_lowercase" {
  type = bool
}

variable "password_require_numbers" {
  type = bool
}

variable "password_require_symbols" {
  type = bool
}

variable "mfa_configuration" {
  type = string
}

variable "email_sending_account" {
  type = string
}

variable "app_client_name" {
  type = string
}

variable "callback_urls" {
  type = list(string)
}

variable "logout_urls" {
  type = list(string)
}

variable "allowed_oauth_scopes" {
  type = list(string)
}

variable "allowed_oauth_flows" {
  type = list(string)
}

variable "allow_signup" {
  type    = bool
  default = true
}

variable "domain_prefix" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

resource "aws_cognito_user_pool" "this" {
  name = var.user_pool_name

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]
  mfa_configuration        = var.mfa_configuration

  admin_create_user_config {
    allow_admin_create_user_only = !var.allow_signup
  }

  email_configuration {
    email_sending_account = var.email_sending_account
  }

  software_token_mfa_configuration {
    enabled = var.mfa_configuration != "OFF"
  }

  password_policy {
    minimum_length    = var.password_minimum_length
    require_lowercase = var.password_require_lowercase
    require_numbers   = var.password_require_numbers
    require_symbols   = var.password_require_symbols
    require_uppercase = var.password_require_uppercase
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    mutable             = true
    required            = true
  }

  tags = merge(var.tags, {
    Name = var.user_pool_name
  })
}

resource "aws_cognito_user_pool_client" "this" {
  name         = var.app_client_name
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret                      = false
  callback_urls                        = var.callback_urls
  logout_urls                          = var.logout_urls
  allowed_oauth_flows                  = var.allowed_oauth_flows
  allowed_oauth_scopes                 = var.allowed_oauth_scopes
  allowed_oauth_flows_user_pool_client = true
  supported_identity_providers         = ["COGNITO"]
  prevent_user_existence_errors        = "ENABLED"

  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
  ]
}

resource "aws_cognito_user_group" "admin" {
  name         = "admin"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Application administrators"
}

resource "aws_cognito_user_group" "policy_manager" {
  name         = "policy-manager"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Users who can install, approve, and activate guardrail policies"
}

resource "aws_cognito_user_group" "guardrails_admin" {
  name         = "guardrails-admin"
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Guardrails Hub validator administrators"
}

resource "aws_cognito_user_pool_domain" "this" {
  count        = var.domain_prefix == "" ? 0 : 1
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.this.id
}

output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  value = aws_cognito_user_pool.this.arn
}

output "app_client_id" {
  value = aws_cognito_user_pool_client.this.id
}

output "issuer" {
  value = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}

output "hosted_ui_domain" {
  value = var.domain_prefix == "" ? "" : "https://${aws_cognito_user_pool_domain.this[0].domain}.auth.${data.aws_region.current.region}.amazoncognito.com"
}

data "aws_region" "current" {}
