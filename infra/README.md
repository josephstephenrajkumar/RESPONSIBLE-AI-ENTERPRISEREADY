# Infrastructure Blueprint

This folder is the Terragrunt/Terraform landing zone for the first enterprise iteration.

The intended deployment keeps the chat flow synchronous:

```text
CloudFront -> S3 frontend
React -> API Gateway HTTP API -> ECS Fargate AI Gateway -> ECS Fargate LiteLLM proxy -> Groq / Bedrock
AI Gateway -> Aurora PostgreSQL
```

No Kafka, SNS, SQS, ACM, Route53, or Lambda broker is included in v1.

## Proposed Structure

```text
infra/
  modules/
    network/
    frontend-s3-cloudfront/
    cognito/
    aurora-postgres/
    ecr/
    ecs-litellm-proxy/
    ecs-ai-gateway/
    api-gateway/
    secrets/
    observability/
  live/
    dev/
    stage/
    prod/
```

## Remote State

Use:

- S3 bucket for Terraform state.
- DynamoDB table for state locking.
- Separate state prefixes per environment.

## First Deployment Order

1. `network`
2. `secrets`
3. `cognito`
4. `aurora-postgres`
5. `ecr`
6. build and push backend image
7. `ecs-litellm-proxy`
8. `ecs-ai-gateway`
9. `api-gateway`
10. `frontend-s3-cloudfront`
11. `observability`
