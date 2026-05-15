# AWS Dev Deployment Runbook

This runbook documents the full `dev` deployment flow for Responsible AI EnterpriseReady.

```text
AWS account: 311464491957
AWS region: ap-southeast-1
AWS profile: responsible-ai-dev
Environment: dev
Project: responsible-ai
```

## 1. Verify Local Tools

Run:

```bash
aws --version
terraform version
terragrunt --version
docker --version
npm --version
```

Required:

```text
AWS CLI v2
Terraform
Terragrunt
Docker
Node/npm
```

## 2. AWS Login

Log in with IAM Identity Center / SSO:

```bash
aws sso login --profile responsible-ai-dev
```

If WSL cannot open the browser:

```bash
aws sso login --profile responsible-ai-dev --no-browser
```

Set the terminal environment:

```bash
export AWS_PROFILE=responsible-ai-dev
export AWS_REGION=ap-southeast-1
export AWS_PAGER=""
```

Verify:

```bash
aws sts get-caller-identity
```

Expected account:

```text
311464491957
```

## 3. Non-Secret Inputs

The non-secret choices are recorded in:

```text
infra-inputs-dev.md
```

Current values:

```text
AWS_ACCOUNT_ID=311464491957
AWS_REGION=ap-southeast-1
ENVIRONMENT=dev
PROJECT_NAME=responsible-ai
RESOURCE_PREFIX=responsible-ai-dev

NETWORK_MODE=new
VPC_CIDR=10.0.0.0/16
PUBLIC_SUBNET_CIDRS=10.0.1.0/24,10.0.2.0/24
PRIVATE_SUBNET_CIDRS=10.0.10.0/24,10.0.11.0/24
DATABASE_SUBNET_CIDRS=10.0.20.0/24,10.0.21.0/24
ENABLE_NAT_GATEWAY=true

DB_NAME=responsible_ai
DB_MASTER_USERNAME=app_admin
DB_MODE=serverless
DB_MIN_ACU=0.5
DB_MAX_ACU=2

COGNITO_ALLOW_SIGNUP=true
COGNITO_MFA=OPTIONAL
USE_CUSTOM_DOMAIN=false
FRONTEND_ORIGINS=http://localhost:5173,http://localhost:3000
COST_PROFILE=dev-low-cost
GUARDRAILS_STRATEGY=disable-temporarily
```

Do not put secrets in markdown files.

Keep these out of git and chat:

```text
AWS_SECRET_ACCESS_KEY
AWS_SESSION_TOKEN
GROQ_API_KEY
database passwords
```

## 4. Deployment Order

Deploy in this order:

```text
1. network
2. secrets
3. cognito
4. aurora-postgres
5. ecr
6. build and push backend image
7. ecs-ai-gateway
8. api-gateway
9. frontend-s3-cloudfront
10. observability
```

## 5. Validate Configuration

Run:

```bash
./deploy.sh validate
```

Warnings about mock dependency outputs are normal before all modules have been applied.

## 6. Foundation Deployment

### 6.1 Network

Initialize:

```bash
./deploy.sh init network
```

This creates the Terraform state backend:

```text
S3 bucket: responsible-ai-terraform-state-dev-311464491957
DynamoDB table: responsible-ai-terraform-locks-dev
```

If AWS output opens in a pager and you see `:` at the bottom, press:

```text
q
```

Then:

```bash
./deploy.sh plan network
./deploy.sh apply network
```

### 6.2 Secrets

```bash
./deploy.sh plan secrets
./deploy.sh apply secrets
```

Created secrets:

```text
responsible-ai-dev/groq_api_key
responsible-ai-dev/database_master_password
responsible-ai-dev/jwt_secret
```

Update the Groq key after `secrets` succeeds:

```bash
aws secretsmanager put-secret-value \
  --secret-id responsible-ai-dev/groq_api_key \
  --secret-string "YOUR_REAL_GROQ_API_KEY"
```

### 6.3 Cognito

```bash
./deploy.sh plan cognito
./deploy.sh apply cognito
```

Note: Cognito requires an MFA method when MFA is `OPTIONAL`. The module enables software-token MFA.

### 6.4 Aurora PostgreSQL

```bash
./deploy.sh plan aurora-postgres
./deploy.sh apply aurora-postgres
```

This can take several minutes.

Configuration:

```text
DB name: responsible_ai
Master username: app_admin
Engine: Aurora PostgreSQL Serverless v2
Min ACU: 0.5
Max ACU: 2
```

### 6.5 ECR

```bash
./deploy.sh plan ecr
./deploy.sh apply ecr
```

Repository:

```text
responsible-ai-dev-ai-gateway
```

## 7. Build And Push Backend Image

Run from the project root.

Get the ECR repository URL:

```bash
ECR_URL=$(aws ecr describe-repositories \
  --repository-names responsible-ai-dev-ai-gateway \
  --query 'repositories[0].repositoryUri' \
  --output text)

echo "$ECR_URL"
```

Login Docker to ECR:

```bash
aws ecr get-login-password --region ap-southeast-1 \
  | docker login --username AWS --password-stdin "$(echo "$ECR_URL" | cut -d/ -f1)"
```

Build:

```bash
docker build -t responsible-ai-gateway:latest ./backend
```

Tag:

```bash
docker tag responsible-ai-gateway:latest "${ECR_URL}:latest"
```

Push:

```bash
docker push "${ECR_URL}:latest"
```

## 8. Deploy ECS AI Gateway

```bash
./deploy.sh plan ecs-ai-gateway
./deploy.sh apply ecs-ai-gateway
```

This creates:

```text
ECS cluster
Fargate task definition
Fargate service
internal Application Load Balancer
CloudWatch log group
IAM roles
```

Check outputs:

```bash
cd infra/live/dev/ecs-ai-gateway
terragrunt output
cd -
```

Tail logs:

```bash
LOG_GROUP=$(cd infra/live/dev/ecs-ai-gateway && terragrunt output -raw log_group_name)
aws logs tail "$LOG_GROUP" --follow
```

## 9. Deploy API Gateway

```bash
./deploy.sh plan api-gateway
./deploy.sh apply api-gateway
```

Get the API endpoint:

```bash
API_ENDPOINT=$(cd infra/live/dev/api-gateway && terragrunt output -raw api_endpoint)
echo "$API_ENDPOINT"
```

Health check:

```bash
curl "${API_ENDPOINT}/health"
```

## 10. Deploy Frontend Hosting

```bash
./deploy.sh plan frontend-s3-cloudfront
./deploy.sh apply frontend-s3-cloudfront
```

Get outputs:

```bash
FRONTEND_BUCKET=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw bucket_name)
CF_DIST_ID=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw cloudfront_distribution_id)
CF_DOMAIN=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw cloudfront_domain_name)

echo "https://${CF_DOMAIN}"
```

## 11. Build And Upload Frontend

Create the production frontend API config:

```bash
API_ENDPOINT=$(cd infra/live/dev/api-gateway && terragrunt output -raw api_endpoint)
echo "VITE_API_BASE=${API_ENDPOINT}" > frontend/.env.production
```

Build:

```bash
cd frontend
npm run build
cd ..
```

Upload:

```bash
aws s3 sync frontend/dist/ "s3://${FRONTEND_BUCKET}/" --delete
```

Invalidate CloudFront:

```bash
aws cloudfront create-invalidation \
  --distribution-id "${CF_DIST_ID}" \
  --paths "/*"
```

Open:

```text
https://<cloudfront-domain>
```

## 12. Update Backend CORS For CloudFront

After CloudFront exists, edit:

```text
infra/live/dev/ecs-ai-gateway/terragrunt.hcl
```

Change:

```hcl
frontend_origins = "http://localhost:5173,http://localhost:3000"
```

To:

```hcl
frontend_origins = "http://localhost:5173,http://localhost:3000,https://YOUR_CLOUDFRONT_DOMAIN"
```

Then redeploy ECS:

```bash
./deploy.sh plan ecs-ai-gateway
./deploy.sh apply ecs-ai-gateway
```

## 13. Deploy Observability

```bash
./deploy.sh plan observability
./deploy.sh apply observability
```

This creates:

```text
CloudWatch ECS CPU alarm
CloudWatch log metric filter for backend errors
```

## 14. Verification Commands

Check VPC:

```bash
aws ec2 describe-vpcs \
  --filters "Name=tag:Project,Values=responsible-ai" \
  --query "Vpcs[*].[VpcId,CidrBlock,State]" \
  --output table
```

Check ECR:

```bash
aws ecr describe-repositories \
  --repository-names responsible-ai-dev-ai-gateway \
  --query 'repositories[0].[repositoryName,repositoryUri]' \
  --output table
```

Check ECS:

```bash
aws ecs list-clusters
aws ecs list-services --cluster responsible-ai-dev-cluster
```

Check API Gateway:

```bash
aws apigatewayv2 get-apis \
  --query "Items[?Name=='responsible-ai-dev-api'].[Name,ApiEndpoint]" \
  --output table
```

## 15. Common Issues

### AWS CLI Opens A Pager

If output pauses with `:` at the bottom:

```text
q
```

Disable pager:

```bash
export AWS_PAGER=""
```

### SSO Token Expired

```bash
aws sso login --profile responsible-ai-dev
export AWS_PROFILE=responsible-ai-dev
export AWS_REGION=ap-southeast-1
```

### Cognito MFA Error

Error:

```text
Invalid MFA Configuration given. SMS MFA, Email MFA, or Software Token MFA must be enabled.
```

The module now enables software-token MFA when MFA is not `OFF`.

### Guardrails Dependency

`guardrails-ai` was removed from required installs because it was quarantined on PyPI during setup. The backend uses regex fallback safety behavior when Guardrails AI is not installed.

### Cost Reminder

These can incur cost while idle:

```text
NAT Gateway
Aurora PostgreSQL
ECS Fargate
CloudFront/S3 usage
CloudWatch logs
```

Destroy the environment when finished testing.

## 16. Destroy

Destroy all modules in reverse order:

```bash
./deploy.sh destroy
```

Or module-by-module:

```bash
./deploy.sh destroy observability
./deploy.sh destroy frontend-s3-cloudfront
./deploy.sh destroy api-gateway
./deploy.sh destroy ecs-ai-gateway
./deploy.sh destroy ecr
./deploy.sh destroy aurora-postgres
./deploy.sh destroy cognito
./deploy.sh destroy secrets
./deploy.sh destroy network
```

Use auto-approve only when you are sure:

```bash
./deploy.sh destroy --auto-approve
```
