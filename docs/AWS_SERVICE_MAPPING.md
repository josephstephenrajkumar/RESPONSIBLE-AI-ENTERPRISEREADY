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
| Responsible AI Gateway runtime | Amazon ECS Fargate | Runs the FastAPI policy enforcement gateway and LLM usage metering |
| Model gateway (LiteLLM proxy) | Amazon ECS Fargate | Holds provider credentials; routes, retries, falls back, budgets and prices every model call |
| Model gateway configuration | Amazon S3 | Private bucket holding `litellm/config.yaml`, loaded by the proxy at start-up |
| Model gateway state | Amazon Aurora PostgreSQL | LiteLLM virtual keys, team budgets and spend log |
| Managed foundation models | Amazon Bedrock | Optional provider reachable from the proxy via its task role (no API key) |
| Container registry | Amazon ECR | Stores backend Docker images |
| Application database | Amazon Aurora PostgreSQL | Stores users, audits, policies, runtime decisions, guardrail violations and `llm_usage_events` |
| Database credentials | AWS Secrets Manager | Stores Aurora credentials, the LiteLLM master key, the gateway's LiteLLM virtual key and provider API keys |
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
| Chat service | Synchronous request/response chat | API Gateway, ECS Fargate (gateway + LiteLLM proxy), Groq / Bedrock |
| Responsible-AI enforcement | Input checks, output checks, redaction, blocking | ECS Fargate AI Gateway |
| FinOps | Metered cost per call, budgets, unit economics, FinOps dashboard | ECS Fargate (gateway metering + LiteLLM spend log), Aurora PostgreSQL |
| AIOps | Availability, latency percentiles, error classes, dependency health, alarms | ECS Fargate, CloudWatch Alarms, X-Ray/OpenTelemetry |
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
