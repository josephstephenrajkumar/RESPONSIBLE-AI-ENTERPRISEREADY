variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "ecs_cluster_name" {
  type = string
}

variable "ecs_service_name" {
  type = string
}

variable "log_group_name" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${local.name}-ecs-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "notBreaching"

  dimensions = {
    ClusterName = var.ecs_cluster_name
    ServiceName = var.ecs_service_name
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_metric_filter" "errors" {
  name           = "${local.name}-backend-errors"
  log_group_name = var.log_group_name
  pattern        = "?ERROR ?Exception ?Traceback"

  metric_transformation {
    name      = "${local.name}-backend-errors"
    namespace = "ResponsibleAI"
    value     = "1"
  }
}

output "ecs_cpu_alarm_name" {
  value = aws_cloudwatch_metric_alarm.ecs_cpu_high.alarm_name
}
