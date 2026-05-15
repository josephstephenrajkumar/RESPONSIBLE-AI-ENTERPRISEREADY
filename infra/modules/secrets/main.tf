variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "secrets" {
  type = map(object({
    description = string
  }))
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name = "${var.project_name}-${var.environment}"
}

resource "random_password" "generated" {
  for_each = {
    for key, value in var.secrets : key => value
    if contains(["database_master_password", "jwt_secret"], key)
  }

  length           = each.key == "database_master_password" ? 24 : 48
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "this" {
  for_each = var.secrets

  name                    = "${local.name}/${each.key}"
  description             = each.value.description
  recovery_window_in_days = 7

  tags = merge(var.tags, {
    Name = "${local.name}-${each.key}"
  })
}

resource "aws_secretsmanager_secret_version" "generated" {
  for_each = random_password.generated

  secret_id     = aws_secretsmanager_secret.this[each.key].id
  secret_string = each.value.result
}

resource "aws_secretsmanager_secret_version" "placeholder" {
  for_each = {
    for key, value in var.secrets : key => value
    if !contains(keys(random_password.generated), key)
  }

  secret_id     = aws_secretsmanager_secret.this[each.key].id
  secret_string = "replace-me"

  lifecycle {
    ignore_changes = [secret_string]
  }
}

output "secret_arns" {
  value = {
    for key, secret in aws_secretsmanager_secret.this : key => secret.arn
  }
}

output "secret_names" {
  value = {
    for key, secret in aws_secretsmanager_secret.this : key => secret.name
  }
}

output "database_master_password" {
  value     = random_password.generated["database_master_password"].result
  sensitive = true
}
