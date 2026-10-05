# Infrastructure Deployment Guide

Step-by-step instructions for provisioning the Responsible AI Enterprise Ready infrastructure with Terragrunt.
The detailed, account-specific flow is [AWS_DEV_DEPLOYMENT_RUNBOOK.md](./AWS_DEV_DEPLOYMENT_RUNBOOK.md).

## Prerequisites

```bash
brew install terraform terragrunt awscli     # terraform >= 1.5, terragrunt 1.x
aws configure --profile <profile>            # or SSO
```

The credentials must resolve to the target account (`aws sts get-caller-identity`). The live configuration in
`infra/live/dev` is bound to one account through `aws_account_id` in `infra/live/dev/terragrunt.hcl`, the Cognito
`domain_prefix`, and the CloudFront origins; retarget those values before deploying to another account.

Required permissions: VPC/EC2, ECS, ECR, RDS (Aurora), API Gateway, Cognito, S3, CloudFront, IAM, Secrets Manager,
CloudWatch, X-Ray, DynamoDB (state locking).

## Modules

| Module | Resources |
|---|---|
| `network` | VPC, public/private/database subnets, route tables, IGW, NAT gateway |
| `secrets` | Secrets Manager secrets (provider key, LiteLLM master/gateway keys, DB password) |
| `cognito` | User pool, app client, hosted-UI domain, groups (`admin`, `policy-manager`, `guardrails-admin`, `finops`, `aiops`) |
| `aurora-postgres` | Aurora PostgreSQL Serverless v2 cluster and instance |
| `ecr` | Backend image repository |
| `ecs-litellm-proxy` | LiteLLM model gateway: S3 config bucket, internal ALB, Fargate service, IAM, alarms |
| `ecs-ai-gateway` | FastAPI policy-enforcement gateway: internal ALB, Fargate service, IAM |
| `api-gateway` | HTTP API with VPC link to the gateway ALB, CORS |
| `frontend-s3-cloudfront` | Private S3 bucket, OAC, CloudFront distribution |
| `observability` | CloudWatch alarm and log metric filter for the gateway |

## Deployment Steps

### Step 1: Bootstrap remote state (once per account)

```bash
(cd infra/live/dev/network && terragrunt --non-interactive backend bootstrap)
```

Terragrunt 1.x does not create the state bucket or lock table during `plan`.

### Step 2: Plan, review, apply each module

```bash
cd infra/live/dev/<module>
terragrunt --non-interactive plan -out=/tmp/<module>.tfplan
terragrunt --non-interactive show /tmp/<module>.tfplan | grep -E "will be|Plan:"
terragrunt --non-interactive apply /tmp/<module>.tfplan
```

`./deploy.sh plan|apply [module]` wraps the same commands in dependency order, but `apply` uses `-auto-approve`;
reserve it for fresh, additive environments you have already planned.

## Deployment Order

1. `network`
2. `secrets` — then store the provider key and the gateway's LiteLLM key
3. `cognito`
4. `aurora-postgres`
5. `ecr` — then build (`--platform linux/amd64`), push and pin the backend image tag
6. `ecs-litellm-proxy`
7. `ecs-ai-gateway`
8. `api-gateway`
9. `frontend-s3-cloudfront` — then build/upload the frontend and add the CloudFront origin to `cognito`, `api-gateway`, `ecs-ai-gateway`
10. `observability`

Expected time: 45–60 minutes end to end (Aurora ~6 min, CloudFront ~5 min, image build/push depends on the machine).

## Verifying Deployment

```bash
aws ec2 describe-vpcs --filters "Name=tag:Project,Values=responsible-ai" --query "Vpcs[*].[VpcId,CidrBlock]" --output table
aws ecs list-services --cluster responsible-ai-dev-cluster
aws ecs list-services --cluster responsible-ai-dev-litellm-cluster
API=$(cd infra/live/dev/api-gateway && terragrunt output -raw api_endpoint)
curl -s "$API/health"
```

Authenticated checks (`/gateway/health`, dashboards) are in the runbook §15.

## Cleanup

Destroy with saved plans, dependents first (runbook §17). Aurora, the NAT gateway, the three Fargate services and the three
internal ALBs incur cost while idle. The dev environment was torn down on 2026-10-05 (snapshot addendum).
