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

variable "litellm_image" {
  type    = string
  default = "ghcr.io/berriai/litellm:main-stable"
}

variable "config_file_path" {
  description = "Local path to litellm/config.yaml; uploaded to S3 and loaded by the proxy at start-up."
  type        = string
}

variable "database_url" {
  description = "Plain postgres URL (postgresql://user:pass@host:5432/db) for LiteLLM virtual keys and spend logs."
  type        = string
  sensitive   = true
}

variable "master_key_secret_arn" {
  type = string
}

variable "provider_secret_arns" {
  description = "Map of provider env var name -> Secrets Manager ARN, e.g. { GROQ_API_KEY = arn }."
  type        = map(string)
  default     = {}
}

variable "otel_exporter_endpoint" {
  type    = string
  default = "http://127.0.0.1:4318/v1/traces"
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "ingress_cidr_blocks" {
  description = "CIDRs allowed to reach the proxy ALB (the AI Gateway service subnets)."
  type        = list(string)
  default     = ["10.0.0.0/8"]
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name       = "${var.project_name}-${var.environment}"
  config_key = "litellm/config.yaml"
}

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# ----------------------------------------------------------------------------
# Config distribution: LiteLLM reads its YAML from S3 at start-up, so a routing
# or budget change is a config upload + service redeploy, not an image build.
# ----------------------------------------------------------------------------
resource "aws_s3_bucket" "config" {
  bucket        = "${local.name}-litellm-config-${data.aws_caller_identity.current.account_id}"
  force_destroy = true

  tags = var.tags
}

resource "aws_s3_bucket_public_access_block" "config" {
  bucket                  = aws_s3_bucket.config.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "config" {
  bucket = aws_s3_bucket.config.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_object" "config" {
  bucket = aws_s3_bucket.config.id
  key    = local.config_key
  source = var.config_file_path
  etag   = filemd5(var.config_file_path)

  tags = var.tags
}

# ----------------------------------------------------------------------------
# Networking: internal ALB in front of the proxy; only the AI Gateway talks to it.
# ----------------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${local.name}-litellm-proxy"
  retention_in_days = 14

  tags = var.tags
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-litellm-alb-sg"
  description = "Internal ALB for LiteLLM proxy"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.name}-litellm-alb-sg" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  for_each = toset(var.ingress_cidr_blocks)

  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = each.value
  from_port         = 80
  ip_protocol       = "tcp"
  to_port           = 80
  description       = "HTTP from AI Gateway"
}

resource "aws_security_group" "service" {
  name        = "${local.name}-litellm-service-sg"
  description = "LiteLLM proxy ECS service"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${local.name}-litellm-service-sg" })
}

resource "aws_vpc_security_group_ingress_rule" "service_from_alb" {
  security_group_id            = aws_security_group.service.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 4000
  ip_protocol                  = "tcp"
  to_port                      = 4000
  description                  = "Proxy traffic from ALB"
}

resource "aws_lb" "this" {
  name               = "${local.name}-litellm"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.private_subnet_ids

  tags = merge(var.tags, { Name = "${local.name}-litellm" })
}

resource "aws_lb_target_group" "this" {
  name        = "${local.name}-litellm"
  port        = 4000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/health/liveliness"
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
  name               = "${local.name}-litellm-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "${local.name}-litellm-execution-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
        Resource = concat([var.master_key_secret_arn], values(var.provider_secret_arns))
      }
    ]
  })
}

resource "aws_iam_role" "task" {
  name               = "${local.name}-litellm-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "task" {
  name = "${local.name}-litellm-task"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.config.arn}/${local.config_key}"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.config.arn
      },
      {
        Effect = "Allow"
        Action = [
          "xray:PutTraceSegments",
          "xray:PutTelemetryRecords",
          "xray:GetSamplingRules",
          "xray:GetSamplingTargets",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
      },
      # Bedrock access lets model_list entries use bedrock/... without any key.
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = "*"
      }
    ]
  })
}

# ----------------------------------------------------------------------------
# ECS
# ----------------------------------------------------------------------------
resource "aws_ecs_cluster" "this" {
  name = "${local.name}-litellm-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${local.name}-litellm-proxy"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "litellm"
      image     = var.litellm_image
      essential = true
      # LiteLLM only consults LITELLM_CONFIG_BUCKET_* when a --config path is
      # given (WORKER_CONFIG must be a string); the path itself is not read.
      command = ["--config", "/app/config.yaml", "--port", "4000"]
      portMappings = [
        { containerPort = 4000, hostPort = 4000, protocol = "tcp" }
      ]
      environment = [
        { name = "LITELLM_CONFIG_BUCKET_NAME", value = aws_s3_bucket.config.id },
        { name = "LITELLM_CONFIG_BUCKET_OBJECT_KEY", value = local.config_key },
        { name = "LITELLM_CONFIG_BUCKET_TYPE", value = "s3" },
        { name = "DATABASE_URL", value = var.database_url },
        { name = "STORE_MODEL_IN_DB", value = "False" },
        { name = "LITELLM_LOG", value = "INFO" },
        { name = "OTEL_EXPORTER", value = "otlp_http" },
        { name = "OTEL_ENDPOINT", value = var.otel_exporter_endpoint },
        { name = "OTEL_SERVICE_NAME", value = "${local.name}-litellm-proxy" },
        { name = "AWS_REGION", value = data.aws_region.current.region }
      ]
      secrets = concat(
        [{ name = "LITELLM_MASTER_KEY", valueFrom = var.master_key_secret_arn }],
        [for env_name, arn in var.provider_secret_arns : { name = env_name, valueFrom = arn }]
      )
      healthCheck = {
        command     = ["CMD-SHELL", "python3 -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:4000/health/liveliness', timeout=3).status==200 else 1)\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.this.name
          awslogs-region        = data.aws_region.current.region
          awslogs-stream-prefix = "litellm"
        }
      }
    },
    {
      name      = "aws-otel-collector"
      image     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.43.2"
      essential = false
      command   = ["--config=/etc/ecs/ecs-default-config.yaml"]
      portMappings = [
        { containerPort = 4318, hostPort = 4318, protocol = "tcp" }
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
  name            = "${local.name}-litellm-proxy"
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
    container_name   = "litellm"
    container_port   = 4000
  }

  depends_on = [aws_lb_listener.http]

  tags = var.tags
}

# ----------------------------------------------------------------------------
# AIOps alarms on the proxy path
# ----------------------------------------------------------------------------
resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  alarm_name          = "${local.name}-litellm-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.this.arn_suffix
    TargetGroup  = aws_lb_target_group.this.arn_suffix
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${local.name}-litellm-unhealthy-hosts"
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

output "proxy_url" {
  description = "Base URL the AI Gateway uses as LITELLM_PROXY_URL."
  value       = "http://${aws_lb.this.dns_name}"
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
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

output "config_bucket" {
  value = aws_s3_bucket.config.id
}
