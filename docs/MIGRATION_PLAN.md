# Migration Plan From Prototype To Enterprise Gateway

## Phase 0 - Current State

The current source began as a local Responsible AI Chat Agent:

- React app served by Vite.
- FastAPI backend run locally.
- SQLite file database.
- Synchronous request handling.
- Global audit records.
- No enterprise user identity.
- Docker Compose for local Jaeger/backend/frontend.

## Phase 1 - Enterprise-Ready Codebase

This new project folder introduces:

- Backend renamed conceptually as an AI Gateway / Policy Enforcement Proxy.
- Async Groq calls through a reusable HTTP client.
- Cognito-compatible JWT validation hooks.
- Local auth bypass for development through `AUTH_REQUIRED=false`.
- User profile upsert on each authenticated request.
- User-scoped audit fields.
- Guardrail violation records.
- `/audit/me` and `/reports/guardrails` APIs.
- Production backend Dockerfile.
- Frontend API client support for bearer tokens.
- Architecture and AWS service mapping documentation.

## Phase 2 - AWS Foundation

Provision with Terragrunt/Terraform:

1. Network: VPC, public/private subnets, security groups, NAT Gateway.
2. Frontend: S3 private bucket and CloudFront distribution.
3. Auth: Cognito User Pool and App Client.
4. Database: Aurora PostgreSQL.
5. Backend: ECR repository and ECS Fargate service.
6. API: API Gateway HTTP API to ECS integration.
7. Configuration: Secrets Manager and Parameter Store.
8. Observability: CloudWatch logs, alarms, and X-Ray/OpenTelemetry.

## Phase 3 - Production Hardening

Add:

- Alembic-managed database migrations.
- Per-user and per-client rate limiting.
- Tenant-aware policy ownership.
- Admin authorization for policy and report endpoints.
- Load tests for hundreds of concurrent chat requests.
- Groq quota validation and provider-side rate planning.
- Circuit breaker behavior for provider outages.
- CloudWatch dashboards and alarms.
- Backup and retention policies.

## Phase 4 - Optional Later Evolution

Only after v1 is stable, consider:

- SNS/SQS or Kafka-style eventing for non-blocking governance workflows.
- Background workers for heavy report generation.
- Custom domain with ACM and Route53.
- Multi-region disaster recovery.
- WebSocket streaming responses.
