# Infrastructure Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying the Responsible AI Enterprise Ready infrastructure to AWS using Terragrunt.

## Prerequisites

### Required Tools

```bash
# Install Terragrunt
brew install terragrunt

# Install Terraform (AWS provider)
brew install terraform

# Install AWS CLI
pip install awscli

# Configure AWS credentials
aws configure
```

### AWS Account Setup

1. Active AWS account with sufficient permissions for:
   - EC2, ECS, ECR, RDS (Aurora)
   - API Gateway, Cognito, S3, CloudFront
   - IAM, VPC, Security Groups
   - Secrets Manager, CloudWatch, X-Ray
   - DynamoDB (for Terraform state locking)

## Deployment Steps

### Step 1: Initialize Infrastructure

```bash
chmod +x deploy.sh

# Initialize all modules (creates S3 backend and DynamoDB lock table)
./deploy.sh init

# Or initialize specific module
./deploy.sh init network
```

### Step 2: Plan Deployment

```bash
# Review planned changes
./deploy.sh plan

# Or plan specific module
./deploy.sh plan network
```

### Step 3: Apply Infrastructure

```bash
# Apply all modules (will prompt for confirmation)
./deploy.sh apply

# Or apply with auto-approval
./deploy.sh apply --auto-approve

# Or apply specific module
./deploy.sh apply network
```

**Expected time**: 20-30 minutes for complete deployment

## Deployment Order

Resources are deployed in the following order to handle dependencies:

1. **Network**: VPC, subnets, security groups, NAT Gateway
2. **Secrets**: AWS Secrets Manager for API keys
3. **Cognito**: User authentication and JWT validation
4. **Aurora PostgreSQL**: Database for audit logs and policies
5. **ECR**: Docker container registry
6. **ECS Fargate**: AI Gateway compute service
7. **API Gateway**: Public HTTPS endpoint
8. **Frontend S3 + CloudFront**: React application hosting
9. **Observability**: CloudWatch, X-Ray monitoring

## Verifying Deployment

```bash
# List created resources
aws ec2 describe-vpcs --filters "Name=tag:Project,Values=responsible-ai"
aws ecs describe-clusters
aws ecr describe-repositories
aws apigatewayv2 get-apis

# Test API endpoint
API_ENDPOINT=$(aws apigatewayv2 get-apis \
  --query "Items[?Name=='responsible-ai-api'].ApiEndpoint" \
  --output text)
curl -X GET "${API_ENDPOINT}/health"
```

## Cleanup

```bash
# Destroy all resources (WARNING: This is irreversible)
./deploy.sh destroy

# Or destroy with auto-approval
./deploy.sh destroy --auto-approve
```

For detailed information, see the documentation files in the `docs/` folder.
