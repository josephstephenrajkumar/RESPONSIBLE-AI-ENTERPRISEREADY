variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "database_url" {
  type      = string
  sensitive = true
}

variable "ecr_repository_url" {
  type = string
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "groq_api_key_secret_arn" {
  type = string
}

variable "guardrails_token_secret_arn" {
  type    = string
  default = ""
}

variable "cognito_region" {
  type = string
}

variable "cognito_user_pool_id" {
  type = string
}

variable "cognito_app_client_id" {
  type = string
}

variable "cognito_domain" {
  type    = string
  default = ""
}

variable "cognito_issuer" {
  type = string
}

variable "frontend_origins" {
  type    = string
  default = ""
}

variable "auth_required" {
  type    = bool
  default = false
}

variable "groq_model" {
  type = string
}

variable "groq_api_url" {
  type = string
}

variable "jaeger_ui_url" {
  type    = string
  default = ""
}

variable "observability_console_url" {
  type    = string
  default = ""
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "cpu" {
  type    = number
  default = 1024
}

variable "memory" {
  type    = number
  default = 2048
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name      = "${var.project_name}-${var.environment}"
  image_uri = "${var.ecr_repository_url}:${var.image_tag}"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.name}-ai-gateway"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-ai-gateway-alb-sg"
  description = "Internal ALB for AI Gateway"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name}-ai-gateway-alb-sg"
  })
}

resource "aws_security_group" "service" {
  name        = "${local.name}-ai-gateway-service-sg"
  description = "ECS service security group"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name}-ai-gateway-service-sg"
  })
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "10.0.0.0/8"
  from_port         = 80
  ip_protocol       = "tcp"
  to_port           = 80
  description       = "HTTP from API Gateway VPC link"
}

resource "aws_vpc_security_group_ingress_rule" "service_from_alb" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  ip_protocol                  = "tcp"
  to_port                      = 8000
  description                  = "App traffic from ALB"
}

resource "aws_lb" "this" {
  name               = "${local.name}-ai-gw"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.private_subnet_ids

  tags = merge(var.tags, {
    Name = "${local.name}-ai-gateway"
  })
}

resource "aws_lb_target_group" "this" {
  name        = "${local.name}-ai-gw"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/health"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 3
  }

  tags = var.tags
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

resource "aws_ecs_cluster" "this" {
  name = "${local.name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-ecs-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "${local.name}-ecs-execution-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "kms:Decrypt"
        ]
        Resource = compact([
          var.groq_api_key_secret_arn,
          var.guardrails_token_secret_arn
        ])
      }
    ]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-ecs-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "task_observability" {
  name = "${local.name}-ecs-task-observability"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
          "xray:GetSamplingStatisticSummaries"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams",
          "logs:DescribeLogGroups",
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${local.name}-ai-gateway"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "ai-gateway"
      image     = local.image_uri
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "AUTH_REQUIRED", value = tostring(var.auth_required) },
        { name = "COGNITO_REGION", value = var.cognito_region },
        { name = "COGNITO_USER_POOL_ID", value = var.cognito_user_pool_id },
        { name = "COGNITO_APP_CLIENT_ID", value = var.cognito_app_client_id },
        { name = "COGNITO_DOMAIN", value = var.cognito_domain },
        { name = "COGNITO_ISSUER", value = var.cognito_issuer },
        { name = "DATABASE_URL", value = var.database_url },
        { name = "GROQ_MODEL", value = var.groq_model },
        { name = "GROQ_API_URL", value = var.groq_api_url },
        { name = "FRONTEND_ORIGINS", value = var.frontend_origins },
        { name = "OTEL_SERVICE_NAME", value = "${local.name}-ai-gateway" },
        { name = "JAEGER_UI_URL", value = var.observability_console_url != "" ? var.observability_console_url : var.jaeger_ui_url },
        { name = "OTEL_EXPORTER", value = "aws_xray_cloudwatch" },
        { name = "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", value = "http://127.0.0.1:4318/v1/traces" }
      ]
      secrets = concat(
        [
          { name = "GROQ_API_KEY", valueFrom = var.groq_api_key_secret_arn }
        ],
        var.guardrails_token_secret_arn == "" ? [] : [
          { name = "GUARDRAILS_TOKEN", valueFrom = var.guardrails_token_secret_arn }
        ]
      )
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "ecs"
        }
      }
    },
    {
      name      = "aws-otel-collector"
      image     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.43.2"
      essential = true
      command   = ["--config=/etc/ecs/ecs-default-config.yaml"]
      portMappings = [
        {
          containerPort = 4318
          hostPort      = 4318
          protocol      = "tcp"
        }
      ]
      environment = [
        { name = "AWS_REGION", value = data.aws_region.current.region }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "adot"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "this" {
  name            = "${local.name}-ai-gateway"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = "ai-gateway"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.http]

  tags = var.tags
}

data "aws_region" "current" {}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "service_security_group_id" {
  value = aws_security_group.service.id
}

output "alb_listener_arn" {
  value = aws_lb_listener.http.arn
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
