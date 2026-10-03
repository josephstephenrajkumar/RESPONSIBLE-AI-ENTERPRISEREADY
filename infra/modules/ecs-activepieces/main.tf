# Activepieces workflow engine (community edition) on ECS Fargate.
# One task runs API + worker + UI (AP_CONTAINER_TYPE=WORKER_AND_APP) behind an
# internal ALB. The AI Gateway owns the control plane (docs/ACTIVEPIECES_INTEGRATION.md).
#
# Dev simplifications, called out in TD-32: the engine shares the application
# Aurora database (its own tables, no name overlap with the gateway or LiteLLM)
# and uses the in-memory queue, so desired_count must stay 1. Production gets
# its own database, ElastiCache Redis (AP_REDIS_TYPE=STANDALONE) and the APP /
# WORKER container split.

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

variable "image" {
  description = "Activepieces image. Pin a release; `latest` lags behind."
  type        = string
  default     = "activepieces/activepieces:0.92.0"
}

variable "container_port" {
  description = "Port the API listens on inside the container (AP_PORT). The worker fetches piece bundles from AP_FRONTEND_URL, so keep it equal to the ALB target port."
  type        = number
  default     = 8080
}

variable "frontend_url" {
  description = "AP_FRONTEND_URL. Empty = the internal ALB URL (worker-facing, keeps bundle fetches inside the VPC). Browsers never reach the engine; the portal's Workflow Studio talks to it through the gateway."
  type        = string
  default     = ""
}

variable "postgres_host" {
  type = string
}

variable "postgres_port" {
  type    = number
  default = 5432
}

variable "postgres_database" {
  type = string
}

variable "postgres_username" {
  type = string
}

variable "postgres_password_secret_arn" {
  description = "Secrets Manager ARN holding the Postgres password (mounted as AP_POSTGRES_PASSWORD)."
  type        = string
}

variable "postgres_use_ssl" {
  description = "Aurora enforces rds.force_ssl=1; the module ships the ap-southeast-1 RDS CA bundle."
  type        = bool
  default     = true
}

variable "encryption_key_secret_arn" {
  description = "AP_ENCRYPTION_KEY: 32 hex characters. Never rotate while connections exist."
  type        = string
}

variable "jwt_secret_secret_arn" {
  description = "AP_JWT_SECRET."
  type        = string
}

variable "pieces_sync_mode" {
  description = "OFFICIAL_AUTO pulls the official catalogue from cloud.activepieces.com (needs egress); NONE for air-gapped installs (install archives only)."
  type        = string
  default     = "OFFICIAL_AUTO"
}

variable "allow_open_sign_up" {
  description = "Let anyone sign up. Keep false: the gateway's service account is created by the first sign-up and builders use it (TD-31)."
  type        = bool
  default     = false
}

variable "webhook_timeout_seconds" {
  type    = number
  default = 120
}

variable "desired_count" {
  description = "Must be 1 while AP_REDIS_TYPE=MEMORY."
  type        = number
  default     = 1
}

variable "cpu" {
  type    = number
  default = 2048
}

variable "memory" {
  type    = number
  default = 4096
}

variable "ingress_cidr_blocks" {
  description = "CIDRs allowed to reach the engine ALB: the VPC (gateway task, API Gateway VPC link, worker self-calls)."
  type        = list(string)
  default     = ["10.0.0.0/8"]
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name         = "${var.project_name}-${var.environment}"
  frontend_url = var.frontend_url != "" ? var.frontend_url : "http://${aws_lb.this.dns_name}"
  # The engine expects the CA as one env value with literal "\n" sequences.
  rds_ca_bundle = replace(file("${path.module}/rds-ca-ap-southeast-1.pem"), "\n", "\\n")
}

data "aws_region" "current" {}

# ----------------------------------------------------------------------------
# Networking: internal ALB; the gateway, the API Gateway VPC link and the
# engine's own worker reach it on :80.
# ----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.name}-activepieces"
  retention_in_days = var.log_retention_days

  tags = var.tags
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-activepieces-alb-sg"
  description = "Internal ALB for the Activepieces engine"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.name}-activepieces-alb-sg" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each = toset(var.ingress_cidr_blocks)

  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 80
  ip_protocol       = "tcp"
  to_port           = 80
  description       = "HTTP from the VPC (gateway, API Gateway VPC link)"
}

resource "aws_security_group" "service" {
  name        = "${local.name}-activepieces-service-sg"
  description = "Activepieces ECS service"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.name}-activepieces-service-sg" })
}

resource "aws_vpc_security_group_ingress_rule" "service_from_alb" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = var.container_port
  ip_protocol                  = "tcp"
  to_port                      = var.container_port
  description                  = "Engine traffic from ALB"
}

resource "aws_lb" "this" {
  name               = "${local.name}-ap"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.private_subnet_ids
  idle_timeout       = 180

  tags = merge(var.tags, { Name = "${local.name}-activepieces" })
}

resource "aws_lb_target_group" "this" {
  name        = "${local.name}-ap"
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/api/v1/flags"
    protocol            = "HTTP"
    timeout             = 10
    unhealthy_threshold = 5
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

# ----------------------------------------------------------------------------
# IAM
# ----------------------------------------------------------------------------
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
  name               = "${local.name}-activepieces-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "${local.name}-activepieces-execution-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
        Resource = [var.encryption_key_secret_arn, var.jwt_secret_secret_arn, var.postgres_password_secret_arn]
      }
    ]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-activepieces-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "task" {
  name = "${local.name}-activepieces-task"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "*"
      }
    ]
  })
}

# ----------------------------------------------------------------------------
# ECS
# ----------------------------------------------------------------------------
resource "aws_ecs_cluster" "this" {
  name = "${local.name}-activepieces-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${local.name}-activepieces"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "activepieces"
      image     = var.image
      essential = true
      portMappings = [
        { containerPort = var.container_port, hostPort = var.container_port, protocol = "tcp" }
      ]
      environment = [
        { name = "AP_PORT", value = tostring(var.container_port) },
        { name = "AP_CONTAINER_TYPE", value = "WORKER_AND_APP" },
        { name = "AP_EDITION", value = "ce" },
        { name = "AP_ENVIRONMENT", value = "prod" },
        { name = "AP_FRONTEND_URL", value = local.frontend_url },
        { name = "AP_DB_TYPE", value = "POSTGRES" },
        { name = "AP_POSTGRES_HOST", value = var.postgres_host },
        { name = "AP_POSTGRES_PORT", value = tostring(var.postgres_port) },
        { name = "AP_POSTGRES_DATABASE", value = var.postgres_database },
        { name = "AP_POSTGRES_USERNAME", value = var.postgres_username },
        { name = "AP_POSTGRES_USE_SSL", value = var.postgres_use_ssl ? "true" : "false" },
        { name = "AP_POSTGRES_SSL_CA", value = var.postgres_use_ssl ? local.rds_ca_bundle : "" },
        { name = "AP_REDIS_TYPE", value = "MEMORY" },
        { name = "AP_EXECUTION_MODE", value = "UNSANDBOXED" },
        { name = "AP_TELEMETRY_ENABLED", value = "false" },
        { name = "AP_ALLOW_OPEN_SIGN_UP", value = var.allow_open_sign_up ? "true" : "false" },
        { name = "AP_PIECES_SYNC_MODE", value = var.pieces_sync_mode },
        { name = "AP_WEBHOOK_TIMEOUT_SECONDS", value = tostring(var.webhook_timeout_seconds) },
        { name = "AP_LOG_LEVEL", value = "info" }
      ]
      secrets = [
        { name = "AP_ENCRYPTION_KEY", valueFrom = var.encryption_key_secret_arn },
        { name = "AP_JWT_SECRET", valueFrom = var.jwt_secret_secret_arn },
        { name = "AP_POSTGRES_PASSWORD", valueFrom = var.postgres_password_secret_arn }
      ]
      healthCheck = {
        command     = ["CMD-SHELL", "node -e \"fetch('http://localhost:${var.container_port}/api/v1/flags').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))\""]
        interval    = 30
        timeout     = 10
        retries     = 5
        startPeriod = 180
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "activepieces"
        }
      }
    }
  ])

  tags = var.tags
}

resource "aws_ecs_service" "this" {
  name                              = "${local.name}-activepieces"
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.this.arn
  desired_count                     = var.desired_count
  launch_type                       = "FARGATE"
  health_check_grace_period_seconds = 300

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = "activepieces"
    container_port   = var.container_port
  }

  depends_on = [aws_lb_listener.http]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${local.name}-activepieces-unhealthy-hosts"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = aws_lb_target_group.this.arn_suffix
  }

  tags = var.tags
}

output "engine_url" {
  description = "Internal base URL the AI Gateway uses as ACTIVEPIECES_API_URL."
  value       = "http://${aws_lb.this.dns_name}"
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "alb_listener_arn" {
  value = aws_lb_listener.http.arn
}

output "service_security_group_id" {
  value = aws_security_group.service.id
}

output "cluster_name" {
  value = aws_ecs_cluster.this.name
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.this.name
}
