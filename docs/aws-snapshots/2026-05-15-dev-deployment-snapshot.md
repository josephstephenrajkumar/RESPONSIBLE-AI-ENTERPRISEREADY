# Responsible AI Dev Deployment Snapshot

Captured: 2026-05-15T08:15:14Z

This is an inventory snapshot of the AWS services deployed for the dev environment. It intentionally excludes secret values. It is safe to keep in Git.

## Account

- AWS account: `311464491957`
- Region: `ap-southeast-1`
- Profile used: `responsible-ai-dev`
- Caller ARN: `arn:aws:sts::311464491957:assumed-role/AWSReservedSSO_AdminAccess_6d208ddf4f9bfcc9/josephrajkumar`

## Public Endpoints

- Frontend CloudFront URL: `https://df22y6w4tmruy.cloudfront.net`
- API Gateway URL: `https://p36xdqfqgj.execute-api.ap-southeast-1.amazonaws.com`
- Cognito Hosted UI domain: `https://responsible-ai-dev-311464491957.auth.ap-southeast-1.amazoncognito.com`
- AWS X-Ray traces console: `https://ap-southeast-1.console.aws.amazon.com/xray/home?region=ap-southeast-1#/traces`

## Frontend

- S3 bucket: `responsible-ai-dev-frontend-311464491957`
- Bucket region: `ap-southeast-1`
- CloudFront distribution ID: `E2E2P1KVJ1RUNS`
- CloudFront domain: `df22y6w4tmruy.cloudfront.net`
- CloudFront status: `Deployed`
- CloudFront origin: `responsible-ai-dev-frontend-311464491957.s3.ap-southeast-1.amazonaws.com`
- Origin access control ID: `E1WWVRNZE23TWT`
- Default root object: `index.html`

## API Gateway

- API name: `responsible-ai-dev-api`
- API ID: `p36xdqfqgj`
- Protocol: `HTTP`
- Endpoint: `https://p36xdqfqgj.execute-api.ap-southeast-1.amazonaws.com`
- Created: `2026-05-14T07:42:57Z`
- CORS origins:
  - `http://localhost:3000`
  - `http://localhost:5173`
  - `https://df22y6w4tmruy.cloudfront.net`

## ECS Backend

- ECS cluster: `responsible-ai-dev-cluster`
- ECS service: `responsible-ai-dev-ai-gateway`
- Service ARN: `arn:aws:ecs:ap-southeast-1:311464491957:service/responsible-ai-dev-cluster/responsible-ai-dev-ai-gateway`
- Status: `ACTIVE`
- Desired/running/pending: `1/1/0`
- Launch type: `FARGATE`
- Task definition: `arn:aws:ecs:ap-southeast-1:311464491957:task-definition/responsible-ai-dev-ai-gateway:6`
- Containers:
  - `ai-gateway`
  - `aws-otel-collector`
- Subnets:
  - `subnet-04a87feffd00667d5`
  - `subnet-0f0ef8cf1dbca1e67`
- Security group: `sg-0c2c258aca02fc3b7`
- Latest rollout state: `COMPLETED`

## Load Balancer

- ALB name: `responsible-ai-dev-ai-gw`
- ALB ARN: `arn:aws:elasticloadbalancing:ap-southeast-1:311464491957:loadbalancer/app/responsible-ai-dev-ai-gw/a29f36006e8264e4`
- DNS: `internal-responsible-ai-dev-ai-gw-338201382.ap-southeast-1.elb.amazonaws.com`
- Scheme: `internal`
- VPC: `vpc-0cb63fd6ed11dc165`
- State: `active`
- Security group: `sg-0bfcae9455fdd4751`
- Target group: `arn:aws:elasticloadbalancing:ap-southeast-1:311464491957:targetgroup/responsible-ai-dev-ai-gw/c723eabd217383d8`

## Container Registry

- ECR repository: `responsible-ai-dev-ai-gateway`
- URI: `311464491957.dkr.ecr.ap-southeast-1.amazonaws.com/responsible-ai-dev-ai-gateway`
- ARN: `arn:aws:ecr:ap-southeast-1:311464491957:repository/responsible-ai-dev-ai-gateway`
- Created: `2026-05-14T15:23:58.563000+08:00`
- Image scanning on push: `true`

## Database

- Aurora cluster ID: `responsible-ai-dev-aurora`
- ARN: `arn:aws:rds:ap-southeast-1:311464491957:cluster:responsible-ai-dev-aurora`
- Engine: `aurora-postgresql`
- Engine version: `17.7`
- Status: `available`
- Database: `responsible_ai`
- Master username: `app_admin`
- Writer instance: `responsible-ai-dev-aurora-1`
- Endpoint: `responsible-ai-dev-aurora.cluster-cja6qiuu6i3g.ap-southeast-1.rds.amazonaws.com`
- Reader endpoint: `responsible-ai-dev-aurora.cluster-ro-cja6qiuu6i3g.ap-southeast-1.rds.amazonaws.com`
- Port: `5432`
- Backup retention: `1` day
- Earliest restorable time: `2026-05-14T07:16:34.625000Z`
- Latest restorable time at capture: `2026-05-15T08:11:34.061000Z`
- Storage encryption: `true`
- Deletion protection: `false`
- Serverless v2 capacity: `0.5` to `2.0` ACU

## Cognito

- User pool name: `responsible-ai-dev`
- User pool ID: `ap-southeast-1_I2vEDxkSh`
- User pool ARN: `arn:aws:cognito-idp:ap-southeast-1:311464491957:userpool/ap-southeast-1_I2vEDxkSh`
- Domain: `responsible-ai-dev-311464491957`
- Estimated users: `1`
- Username attribute: `email`
- Auto verified attribute: `email`
- Deletion protection: `INACTIVE`
- MFA: `OPTIONAL`
- Password minimum length: `12`
- Groups:
  - `admin`
  - `policy-manager`
  - `guardrails-admin`
- `joseph.stephenr@gmail.com` group membership at capture: `policy-manager`

## Secrets Manager

Secret values were not captured.

- `responsible-ai-dev/groq_api_key`
- `responsible-ai-dev/jwt_secret`
- `responsible-ai-dev/database_master_password`
- `responsible-ai-dev/guardrails_token`

## CloudWatch Logs And Traces

- ECS log group: `/ecs/responsible-ai-dev-ai-gateway`
- Log retention: `14` days
- Stored bytes at capture: `14633`
- Trace exporter: `aws_xray_cloudwatch`
- Trace collector sidecar: `aws-otel-collector`
- OTLP trace endpoint inside task: `http://127.0.0.1:4318/v1/traces`

## Teardown Notes

Terraform/Terragrunt manages the main project resources. To stop ongoing cost, destroy the modules in dependency-safe order, with CloudFront and ECS first and network last.

Suggested order:

1. `frontend-s3-cloudfront`
2. `api-gateway`
3. `ecs-ai-gateway`
4. `aurora-postgres`
5. `cognito`
6. `ecr`
7. `secrets`
8. `network`

Before teardown, decide whether to create a final RDS cluster snapshot. A final database snapshot preserves data, but it can continue to incur storage cost.
