# Setup Document

The current AWS deployment runbook is maintained here:

[AWS Dev Deployment Runbook](docs/AWS_DEV_DEPLOYMENT_RUNBOOK.md)

Use that document for the latest foundation deployment, backend image push, ECS/API/frontend deployment, verification, troubleshooting, and cleanup steps.

The older notes below are retained only as historical context.

Here is the previous step-by-step path.

1. Install Local Tools

You need:

bash



aws --version
terraform version
terragrunt --version
docker --version
npm --version



If missing, install:


AWS CLI v2

Terraform

Terragrunt

Docker

Node/npm


Then authenticate AWS:

bash



aws configure
aws sts get-caller-identity



This repo defaults to:

text



Region: ap-southeast-1
Environment: dev
Project: responsible-ai



2. Confirm The Infra Gap

Run:

bash



find infra/modules -maxdepth 2 -type f
find infra/live/dev -maxdepth 2 -type f



You should currently see only module README.md files under infra/modules. That means Terraform implementation still needs to be written for:

text



network
secrets
cognito
aurora-postgres
ecr
ecs-ai-gateway
api-gateway
frontend-s3-cloudfront
observability



Until those modules have .tf files, deployment commands will not provision real AWS resources.

3. Create Terraform Remote State

The script can create:

text



S3 bucket: responsible-ai-terraform-state-dev
DynamoDB table: responsible-ai-terraform-locks-dev
Region: ap-southeast-1



Command:

bash



./deploy.sh init network



But note: because the current script always checks prerequisites and sets up backend during init, this should create the backend bucket/table before trying Terragrunt init.

If the S3 bucket name is already taken globally, change PROJECT_NAME in deploy.sh, for example:

bash



PROJECT_NAME="responsible-ai-yourname"



4. Implement Or Generate Terraform Modules

Before full deployment, each module needs real Terraform. The expected dependency order from infra/README.md is:

text



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



The minimum practical AWS resources are:

text



network:
  VPC, public/private/database subnets, route tables, IGW, NAT Gateway, security groups

secrets:
  Secrets Manager entries for GROQ_API_KEY, database password, JWT/Cognito-related values

cognito:
  User pool and app client

aurora-postgres:
  Aurora PostgreSQL cluster, subnet group, security group, DB secret/output endpoint

ecr:
  ECR repository for backend image

ecs-ai-gateway:
  ECS cluster, task definition, Fargate service, ALB or service integration target, task role, execution role, CloudWatch logs

api-gateway:
  HTTP API forwarding to the backend service

frontend-s3-cloudfront:
  private S3 bucket, CloudFront distribution, Origin Access Control

observability:
  CloudWatch alarms/log groups, optional X-Ray/OTel config



5. Initialize Infra

Once modules exist:

bash



./deploy.sh init



Or module-by-module:

bash



./deploy.sh init network
./deploy.sh init secrets
./deploy.sh init cognito
./deploy.sh init aurora-postgres
./deploy.sh init ecr



6. Plan Infra

Plan one module first:

bash



./deploy.sh plan network



Then continue in order:

bash



./deploy.sh plan secrets
./deploy.sh plan cognito
./deploy.sh plan aurora-postgres
./deploy.sh plan ecr



After the image is pushed, plan:

bash



./deploy.sh plan ecs-ai-gateway
./deploy.sh plan api-gateway
./deploy.sh plan frontend-s3-cloudfront
./deploy.sh plan observability



7. Apply Base Infra

Apply the dependency chain:

bash



./deploy.sh apply network
./deploy.sh apply secrets
./deploy.sh apply cognito
./deploy.sh apply aurora-postgres
./deploy.sh apply ecr



8. Store Runtime Secrets

Put your Groq key in Secrets Manager. The intended backend env values are from backend/.env.example:

text



GROQ_API_KEY
GROQ_MODEL
GROQ_API_URL
AUTH_REQUIRED=true
COGNITO_REGION
COGNITO_USER_POOL_ID
COGNITO_APP_CLIENT_ID
COGNITO_ISSUER
DATABASE_URL
FRONTEND_ORIGINS



For AWS, DATABASE_URL should look like:

text



postgresql+psycopg2://user:password@aurora-endpoint:5432/responsible_ai



9. Build And Push Backend Image

After the ECR module exists and is applied, get your account ID:

bash



AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=ap-southeast-1
ECR_REPO=responsible-ai-dev-ai-gateway
IMAGE_TAG=$(git rev-parse --short HEAD)



Login to ECR:

bash



aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"



Build and push:

bash



docker build -t "$ECR_REPO:$IMAGE_TAG" ./backend

docker tag "$ECR_REPO:$IMAGE_TAG" \
  "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:$IMAGE_TAG"

docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECR_REPO:$IMAGE_TAG"



The backend Dockerfile runs FastAPI through Gunicorn/Uvicorn on port 8000.

10. Deploy Backend Service And API

Once the image exists in ECR:

bash



./deploy.sh apply ecs-ai-gateway
./deploy.sh apply api-gateway



Capture the API Gateway URL. It should become the frontend API base:

text



https://your-api-id.execute-api.ap-southeast-1.amazonaws.com



11. Build Frontend

Set the API URL for Vite:

bash



cd frontend
cp .env.example .env.production



Edit:

text



VITE_API_BASE=https://your-api-gateway-url



Build:

bash



npm install
npm run build



This creates:

text



frontend/dist



12. Deploy Frontend Hosting

Apply the frontend infra:

bash



cd ..
./deploy.sh apply frontend-s3-cloudfront



Then upload the built assets to the S3 bucket created by the frontend module:

bash



aws s3 sync frontend/dist s3://YOUR_FRONTEND_BUCKET_NAME --delete



Invalidate CloudFront:

bash



aws cloudfront create-invalidation \
  --distribution-id YOUR_DISTRIBUTION_ID \
  --paths "/*"



Your app URL will be the CloudFront default domain:

text



https://xxxxxxxxxxxxx.cloudfront.net



13. Update CORS / Frontend Origins

After CloudFront exists, set backend FRONTEND_ORIGINS to:

text



https://xxxxxxxxxxxxx.cloudfront.net



Then redeploy ECS so the backend picks it up.

14. Smoke Test

Check backend health through API Gateway:

bash



curl https://your-api-gateway-url/health



Open the frontend:

text



https://your-cloudfront-domain.cloudfront.net



Then test:

text



register/login via Cognito
send chat message
verify audit/reporting pages
check CloudWatch logs for ECS task



15. Destroy When Needed

Destroy in reverse order:

bash



./deploy.sh destroy observability
./deploy.sh destroy frontend-s3-cloudfront
./deploy.sh destroy api-gateway
./deploy.sh destroy ecs-ai-gateway
./deploy.sh destroy ecr
./deploy.sh destroy aurora-postgres
./deploy.sh destroy cognito
./deploy.sh destroy secrets
./deploy.sh destroy network



Or, once the modules are fully implemented:

bash



./deploy.sh destroy



Bottom line: the deployment design is already documented and deploy.sh has the orchestration shape, but the Terraform modules still need to be built before AWS infra creation will actually work. The next useful step would be implementing those modules, starting with network, secrets, cognito, aurora-postgres, and ecr.
