# Dev Deployment Snapshot — account 767141477889 (2026-10-02)

Inventory of the AWS resources deployed for the dev environment by the Sprint 1 deployment.
It intentionally excludes secret values and is safe to keep in Git. The previous snapshot
(`2026-05-15`) described the earlier deployment in account 311464491957, which this
deployment does not touch.

## Entry points

- Frontend (CloudFront): `https://d12wylhj234wu3.cloudfront.net`
- API (API Gateway HTTP API): `https://0nl4sfks87.execute-api.ap-southeast-1.amazonaws.com`
- Cognito Hosted UI: `https://responsible-ai-dev-767141477889.auth.ap-southeast-1.amazoncognito.com`
- LiteLLM proxy (VPC-internal only): `http://internal-responsible-ai-dev-litellm-1635444095.ap-southeast-1.elb.amazonaws.com`

## Identity

- AWS account: `767141477889`, region `ap-southeast-1`
- Terraform state: S3 `responsible-ai-terraform-state-dev-767141477889`, lock table `responsible-ai-terraform-locks-dev`
- Deployed commit: `aed1bb5` on `feature/real-ragas-trulens-eval`

## Network

- VPC `vpc-0f6b4c53dd9d38e19` (`10.0.0.0/16`), 2 public / 2 private / 2 database subnets, 1 NAT gateway

## Cognito

- User pool `ap-southeast-1_FMGf5Zs0e` (`responsible-ai-dev`), app client `33v9cjft60qcjgtkkjdlulhjrc`
- Groups: `admin`, `policy-manager`, `guardrails-admin`, `finops`, `aiops` (the `model-admin` role is honoured by the gateway but has no Cognito group yet; `admin` covers it)
- Auth flows: SRP (hosted UI/PKCE), refresh, and `ADMIN_USER_PASSWORD_AUTH` (dev smoke tests only)
- Callback / logout URLs include `https://d12wylhj234wu3.cloudfront.net` and localhost dev ports
- Users: `joseph.stephenr@gmail.com` (group `admin`, invited 2026-10-02); smoke tests used temporary users that were deleted

## Secrets Manager (`responsible-ai-dev/*`)

`groq_api_key` (set), `litellm_master_key` (generated), `litellm_gateway_key` (dev: copy of master key — TD-25),
`litellm_salt_key` (generated; encrypts runtime-added model credentials), `anthropic_api_key` / `openai_api_key`
(placeholders, not mounted), `database_master_password` (generated), `jwt_secret` (generated, unused — TD-17)

## Aurora PostgreSQL

- Cluster `responsible-ai-dev-aurora` (Serverless v2, 0.5–2 ACU), database `responsible_ai`, user `app_admin`
- Endpoint `responsible-ai-dev-aurora.cluster-cp80i0820zta.ap-southeast-1.rds.amazonaws.com`
- Holds the application tables (audit, policies, `llm_usage_events`, `gateway_settings`) and LiteLLM's `LiteLLM_*` tables (models, credentials, keys, teams, MCP servers, guardrails, spend)

## ECR

- `767141477889.dkr.ecr.ap-southeast-1.amazonaws.com/responsible-ai-dev-ai-gateway` — tags `aed1bb5`, `latest`

## ECS

- LiteLLM proxy: cluster `responsible-ai-dev-litellm-cluster`, service `responsible-ai-dev-litellm-proxy`
  (0.5 vCPU / 1 GB, image `ghcr.io/berriai/litellm:main-stable`, `STORE_MODEL_IN_DB=True`), internal ALB `responsible-ai-dev-litellm`,
  config from S3 bucket `responsible-ai-dev-litellm-config-767141477889` key `litellm/config.yaml`,
  log group `/ecs/responsible-ai-dev-litellm-proxy`
- AI Gateway: cluster `responsible-ai-dev-cluster`, service `responsible-ai-dev-ai-gateway`
  (1 vCPU / 2 GB, image tag `aed1bb5`), internal ALB `responsible-ai-dev-ai-gw`, log group `/ecs/responsible-ai-dev-ai-gateway`
- Gateway task mounts `LITELLM_API_KEY` and `LITELLM_ADMIN_API_KEY` (Proxy Manager; both are the master key in dev — TD-25); `GROQ_API_KEY` is mounted only in the proxy task
- Enabled providers for the admin model catalogue: `groq`, `bedrock` (proxy task role)

## API Gateway

- HTTP API `responsible-ai-dev-api`, VPC link to the gateway ALB, CORS origins: localhost dev ports and `https://d12wylhj234wu3.cloudfront.net`

## Frontend

- S3 bucket `responsible-ai-dev-frontend-767141477889` (private, OAC), CloudFront distribution `E3SBHD9QG7B984` (`d12wylhj234wu3.cloudfront.net`)
- Built with `VITE_API_BASE=https://0nl4sfks87.execute-api.ap-southeast-1.amazonaws.com`

## Observability

- CloudWatch alarms: gateway ECS CPU > 80 %, gateway log error filter, LiteLLM ALB target 5xx, LiteLLM unhealthy hosts
- Traces: ADOT sidecars on both services → X-Ray

## Runtime-added models (LiteLLM database, via the admin catalogue)

- `nova-micro` → `bedrock/apac.amazon.nova-micro-v1:0` (ap-southeast-1), added 2026-10-02 and verified in chat.
- Anthropic-on-Bedrock models are blocked until the account's Anthropic use-case form is submitted (see MODEL_CATALOG.md).

## Models (LiteLLM `model_list`)

`openai/gpt-oss-120b` (default chat), `openai/gpt-oss-20b`, groups `chat-default`, `judge-fast` (gpt-oss-20b,
`reasoning_effort: low`); fallback `openai/gpt-oss-120b → openai/gpt-oss-20b`. The Groq account does not serve
the llama-3.x models, so they are commented out in `litellm/config.yaml`.

## Monthly cost drivers (approximate)

NAT gateway (~$35 + data), Aurora Serverless v2 at 0.5 ACU minimum (~$45), two Fargate services (~$50),
two internal ALBs (~$35), CloudFront/S3/API Gateway/Secrets Manager (low, usage-based). Expect roughly
$170–200/month at idle; see `docs/TECH_DEBT.md` for consolidation options.

## Teardown order

`observability → frontend-s3-cloudfront → api-gateway → ecs-ai-gateway → ecs-litellm-proxy → ecr → aurora-postgres → cognito → secrets → network`
(`terragrunt destroy` per module). Decide on a final Aurora snapshot before destroying the cluster.
