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
- Async model calls through a reusable HTTP client (now `app.llm_client` → LiteLLM proxy).
- Cognito-compatible JWT validation hooks.
- Local auth bypass for development through `AUTH_REQUIRED=false`.
- User profile upsert on each authenticated request.
- User-scoped audit fields.
- Guardrail violation records.
- `/audit/me` and `/reports/guardrails` APIs.
- Production backend Dockerfile.
- Frontend API client support for bearer tokens.
- Architecture and AWS service mapping documentation.

## Phase 2 - AWS Foundation — done (dev, account 767141477889, 2026-10-02)

Provisioned with Terragrunt/Terraform (see `docs/aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md`):

1. Network: VPC, public/private subnets, security groups, NAT Gateway.
2. Frontend: S3 private bucket and CloudFront distribution.
3. Auth: Cognito User Pool and App Client.
4. Database: Aurora PostgreSQL.
5. Backend: ECR repository and ECS Fargate service (AI Gateway).
6. Model gateway: ECS Fargate LiteLLM proxy with S3-distributed config; the gateway holds no provider key.
7. API: API Gateway HTTP API to ECS integration.
8. Configuration: Secrets Manager.
9. Observability: CloudWatch logs, alarms, and X-Ray/OpenTelemetry (ADOT sidecars on both services).

## Phase 3 - Production Hardening — in progress (roadmap Sprints 2–4)

Done: admin authorization for policy and report endpoints (Cognito groups incl. `finops`/`aiops`); retries, fallbacks
and cost metering at the LiteLLM proxy; FinOps and AIOps dashboards. Remaining:

- Alembic-managed database migrations.
- Per-tenant/team budgets and RPM/TPM limits via LiteLLM virtual keys.
- Tenant-aware policy ownership.
- Load tests for hundreds of concurrent chat requests.
- Provider quota planning and tuned circuit-breaker settings (`allowed_fails`, `cooldown_time`) from load tests.
- CloudWatch dashboards and alarms.
- Backup and retention policies.

## Phase 4 - Optional Later Evolution

Only after v1 is stable, consider:

- SNS/SQS or Kafka-style eventing for non-blocking governance workflows.
- Background workers for heavy report generation.
- Custom domain with ACM and Route53.
- Multi-region disaster recovery.
- WebSocket streaming responses.
