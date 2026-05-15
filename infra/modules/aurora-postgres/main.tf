variable "project_name" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "database_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group_id" {
  type    = string
  default = null
}

variable "allowed_cidr_blocks" {
  type    = list(string)
  default = []
}

variable "db_name" {
  type = string
}

variable "master_username" {
  type = string
}

variable "master_password" {
  type      = string
  sensitive = true
}

variable "min_capacity" {
  type = number
}

variable "max_capacity" {
  type = number
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  name = "${var.project_name}-${var.environment}"
}

resource "aws_security_group" "db" {
  name        = "${local.name}-aurora-sg"
  description = "Aurora PostgreSQL access"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${local.name}-aurora-sg"
  })
}

resource "aws_vpc_security_group_ingress_rule" "ecs_to_db" {
  count = var.ecs_security_group_id == null ? 0 : 1

  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = var.ecs_security_group_id
  from_port                    = 5432
  ip_protocol                  = "tcp"
  to_port                      = 5432
  description                  = "PostgreSQL from ECS"
}

resource "aws_vpc_security_group_ingress_rule" "cidr_to_db" {
  for_each = toset(var.allowed_cidr_blocks)

  security_group_id = aws_security_group.db.id
  cidr_ipv4         = each.value
  from_port         = 5432
  ip_protocol       = "tcp"
  to_port           = 5432
  description       = "PostgreSQL from allowed CIDR"
}

resource "aws_db_subnet_group" "this" {
  name       = "${local.name}-aurora-subnets"
  subnet_ids = var.database_subnet_ids

  tags = merge(var.tags, {
    Name = "${local.name}-aurora-subnets"
  })
}

resource "aws_rds_cluster" "this" {
  cluster_identifier     = "${local.name}-aurora"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned"
  database_name          = var.db_name
  master_username        = var.master_username
  master_password        = var.master_password
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  storage_encrypted      = true
  skip_final_snapshot    = true

  serverlessv2_scaling_configuration {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }

  tags = merge(var.tags, {
    Name = "${local.name}-aurora"
  })
}

resource "aws_rds_cluster_instance" "this" {
  count = 1

  identifier         = "${local.name}-aurora-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.this.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version

  tags = merge(var.tags, {
    Name = "${local.name}-aurora-${count.index + 1}"
  })
}

output "cluster_arn" {
  value = aws_rds_cluster.this.arn
}

output "cluster_endpoint" {
  value = aws_rds_cluster.this.endpoint
}

output "cluster_reader_endpoint" {
  value = aws_rds_cluster.this.reader_endpoint
}

output "database_name" {
  value = aws_rds_cluster.this.database_name
}

output "security_group_id" {
  value = aws_security_group.db.id
}

output "database_url" {
  value     = "postgresql+psycopg2://${var.master_username}:${var.master_password}@${aws_rds_cluster.this.endpoint}:5432/${var.db_name}"
  sensitive = true
}
