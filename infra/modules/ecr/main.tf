variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "repository_name" {
  type    = string
  default = null
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name = coalesce(var.repository_name, "${var.project_name}-${var.environment}-ai-gateway")
}

resource "aws_ecr_repository" "this" {
  name                 = local.name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(var.tags, {
    Name = local.name
  })
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the last 20 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

output "repository_name" {
  value = aws_ecr_repository.this.name
}

output "repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "repository_arn" {
  value = aws_ecr_repository.this.arn
}
