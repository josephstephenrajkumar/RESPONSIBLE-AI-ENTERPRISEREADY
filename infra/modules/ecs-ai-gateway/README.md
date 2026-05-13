# ECS AI Gateway Module

Planned resources:

- ECS cluster
- Fargate service for FastAPI AI Gateway
- Task definition using the ECR backend image
- ECS task role for Secrets Manager, Parameter Store, CloudWatch, and X-Ray
- Autoscaling policy
- Security group allowing inbound only from API Gateway integration path

The service handles synchronous chat requests and calls Groq directly.
