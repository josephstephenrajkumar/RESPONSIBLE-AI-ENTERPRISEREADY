# AWS Service Mapping

## Application Component To AWS Service

| Business / Application Component | AWS Service | Purpose |
|---|---|---|
| Public web application | Amazon CloudFront | Default HTTPS entry point and global cache for the React app |
| Static frontend assets | Amazon S3 | Private bucket containing the built React/Vite assets |
| Frontend origin protection | CloudFront Origin Access Control | Keeps S3 private and reachable only through CloudFront |
| User registration and login | Amazon Cognito User Pool | Managed user directory, registration, password flow, and JWT issuer |
| Browser auth client | Cognito App Client | OAuth/JWT client used by the React app |
| Public backend API endpoint | Amazon API Gateway HTTP API | Default HTTPS API endpoint without custom domain |
| Responsible AI Gateway runtime | Amazon ECS Fargate | Runs the FastAPI policy enforcement proxy |
| Container registry | Amazon ECR | Stores backend Docker images |
| Application database | Amazon Aurora PostgreSQL | Stores users, audits, policies, runtime decisions, and guardrail violations |
| Database credentials | AWS Secrets Manager | Stores Aurora credentials and provider API keys |
| Non-secret configuration | AWS Systems Manager Parameter Store | Stores environment-specific values such as URLs and feature flags |
| Network isolation | Amazon VPC | Isolates backend and database resources |
| Backend and database network zones | Private subnets | Keeps ECS tasks and Aurora away from direct public inbound access |
| Outbound provider calls | NAT Gateway | Lets private ECS tasks call Groq and other public APIs |
| Access control | AWS IAM | Task roles, deployment roles, and least-privilege service permissions |
| Runtime logs | Amazon CloudWatch Logs | Stores backend application logs |
| Metrics and alarms | CloudWatch Metrics and Alarms | Tracks API health, task health, database load, and error rates |
| Distributed tracing | AWS X-Ray / OpenTelemetry | Traces request flow through API Gateway, ECS, database, and Groq calls |
| Infrastructure deployment | Terragrunt + Terraform | Repeatable environment provisioning |
| Terraform state | S3 backend bucket | Stores remote Terraform state |
| Terraform state locking | DynamoDB | Prevents concurrent state writes |

## Business Capability Mapping

| Business Capability | Supporting Components | AWS Services |
|---|---|---|
| User onboarding | Registration, login, token issuance | Cognito |
| Chat service | Synchronous request/response chat | API Gateway, ECS Fargate, Groq external API |
| Responsible-AI enforcement | Input checks, output checks, redaction, blocking | ECS Fargate AI Gateway |
| User accountability | User-scoped audit trail | Cognito, Aurora PostgreSQL |
| Compliance reporting | Guardrail violation reports by user/client/agent | Aurora PostgreSQL, backend report APIs |
| Policy governance | Policy CRUD, approval, activation, runtime decisions | ECS Fargate, Aurora PostgreSQL |
| Operational visibility | Logs, metrics, traces, alarms | CloudWatch, X-Ray/OpenTelemetry |
| Secure configuration | Secrets and non-secret environment values | Secrets Manager, Parameter Store |
| Cost-efficient frontend delivery | Static asset hosting and caching | S3, CloudFront |

## V1 Service List

The first iteration provisions or prepares for:

1. Amazon S3
2. Amazon CloudFront
3. Amazon Cognito
4. Amazon API Gateway HTTP API
5. Amazon ECS Fargate
6. Amazon ECR
7. Amazon Aurora PostgreSQL
8. AWS Secrets Manager
9. AWS Systems Manager Parameter Store
10. Amazon VPC
11. NAT Gateway
12. Security Groups
13. AWS IAM
14. Amazon CloudWatch
15. AWS X-Ray / OpenTelemetry
16. S3 backend bucket for Terraform state
17. DynamoDB table for Terraform state locking

Not included in v1:

- ACM
- Route53
- Kafka / Amazon MSK
- SNS
- SQS
- Lambda chat broker
- Custom domain
