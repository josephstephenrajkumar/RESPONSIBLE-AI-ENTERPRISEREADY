variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "alb_listener_arn" {
  type = string
}

variable "allowed_origins" {
  type    = list(string)
  default = ["http://localhost:5173", "http://localhost:3000"]
}

variable "name_suffix" {
  description = "Suffix for the API and VPC link names when more than one HTTP API exists (for example \"-workflows\")."
  type        = string
  default     = ""
}

variable "enable_cors" {
  description = "Attach a CORS configuration. Disable when the backend sets its own CORS headers (the Activepieces engine)."
  type        = bool
  default     = true
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name = "${var.project_name}-${var.environment}${var.name_suffix}"
}

resource "aws_apigatewayv2_vpc_link" "this" {
  name               = "${local.name}-vpc-link"
  subnet_ids         = var.private_subnet_ids
  security_group_ids = []

  tags = var.tags
}

resource "aws_apigatewayv2_api" "this" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"

  dynamic "cors_configuration" {
    for_each = var.enable_cors ? [1] : []
    content {
      allow_credentials = true
      allow_headers     = ["authorization", "content-type"]
      allow_methods     = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
      allow_origins     = var.allowed_origins
      max_age           = 300
    }
  }

  tags = var.tags
}

resource "aws_apigatewayv2_integration" "this" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "HTTP_PROXY"
  integration_method     = "ANY"
  integration_uri        = var.alb_listener_arn
  connection_type        = "VPC_LINK"
  connection_id          = aws_apigatewayv2_vpc_link.this.id
  payload_format_version = "1.0"
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.this.id}"
}

resource "aws_apigatewayv2_route" "root" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "ANY /"
  target    = "integrations/${aws_apigatewayv2_integration.this.id}"
}

variable "throttling_burst_limit" {
  description = "Default route burst limit (requests). Protects the gateway and the MCP endpoint from floods."
  type        = number
  default     = 100
}

variable "throttling_rate_limit" {
  description = "Default route steady-state limit (requests per second)."
  type        = number
  default     = 50
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.throttling_burst_limit
    throttling_rate_limit  = var.throttling_rate_limit
  }

  tags = var.tags
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  value = aws_apigatewayv2_api.this.api_endpoint
}
