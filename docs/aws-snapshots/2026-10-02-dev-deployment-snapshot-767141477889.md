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

## Addendum — Proxy Manager completeness (2026-10-02, later)

- LiteLLM proxy: `litellm/config.yaml` trimmed to bootstrap-only and re-uploaded to S3 (`responsible-ai-dev-litellm-config-767141477889/litellm/config.yaml`); service `responsible-ai-dev-litellm-proxy` force-redeployed (task definition `:2`, image unchanged).
- AI Gateway: image `f380f45` pushed to ECR, task definition `responsible-ai-dev-ai-gateway:6`, rollout COMPLETED.
- Frontend: rebuilt and uploaded to `responsible-ai-dev-frontend-767141477889`, CloudFront `E3SBHD9QG7B984` invalidated.
- Smoke (temporary Cognito admin, deleted afterwards):
  - `GET /gateway/admin/litellm-config` → seeded `true`; router retries 2 / timeout 30 / cooldown 30 / simple-shuffle; fallback chain present; callbacks `otel`; 15 available callbacks; 27 cache fields; 39 general-settings fields.
  - `POST /config/update` num_retries 3 → read back 3 → restored 2 (persisted in the proxy DB).
  - `POST /config/field/update` max_parallel_requests=100 → `/config/list` shows `stored_in_db: true`.
  - Cache test without Redis → clear "connection refused" message (ElastiCache is Sprint 5).
  - Key rotation (gateway-side) → new key issued with the same alias and model scope; one key per alias remains; verified on the local proxy that the old key is rejected (401) immediately. Note: LiteLLM's `/key/info` still answers 200 for a deleted key (cache); use `/key/list` as the source of truth.
  - Chat through the proxy with DB-held router settings → 200 "OK".
  - Refresh token issued by Cognito (frontend session refresh depends on it).

## Addendum 2026-10-03 — Workflow Apps (Activepieces) deployed

Applied from saved, reviewed plans (secrets 6 added; ecs-activepieces 17 added; api-gateway-workflows 6 added;
ecs-ai-gateway rolled three times the same day, final task definition `:9`, image `1c6425c`). Design: [ACTIVEPIECES_INTEGRATION.md](../ACTIVEPIECES_INTEGRATION.md).

- Engine (public, for the embedded builder and chat): `https://kv84d4ljc6.execute-api.ap-southeast-1.amazonaws.com`
  (HTTP API `responsible-ai-dev-workflows-api`, own VPC link, no API Gateway CORS; the engine sets its own)
- Engine (internal, used by the gateway and by the engine worker as `AP_FRONTEND_URL`):
  `http://internal-responsible-ai-dev-ap-524368449.ap-southeast-1.elb.amazonaws.com`
- ECS: cluster `responsible-ai-dev-activepieces-cluster`, service `responsible-ai-dev-activepieces` (1 task, 2 vCPU / 4 GB,
  image `activepieces/activepieces:0.92.0` from Docker Hub via NAT), log group `/ecs/responsible-ai-dev-activepieces`,
  ALB `responsible-ai-dev-ap`, health check `/api/v1/flags`, circuit breaker with rollback
- Database: shares the Aurora database `responsible_ai` over SSL (RDS CA bundle in the module); queue in-memory
  (`AP_REDIS_TYPE=MEMORY`), so `desired_count` stays 1 (TD-32 dev simplifications)
- Secrets: `responsible-ai-dev/activepieces_encryption_key`, `activepieces_jwt_secret`, `activepieces_service_password`
  (values set out of band; the gateway task mounts the service password)
- Gateway task env: `ACTIVEPIECES_ENABLED=true`, `ACTIVEPIECES_API_URL` = internal ALB, `ACTIVEPIECES_PUBLIC_URL` = HTTP API,
  `ACTIVEPIECES_GATEWAY_URL` = gateway internal ALB, `ACTIVEPIECES_LITELLM_URL` = proxy internal ALB, `ACTIVEPIECES_PIECES_DIR=/app/pieces`
- Startup bootstrap on the fresh engine: service account signed up as platform admin, pieces
  `@responsible-ai/piece-responsible-ai-gateway` 0.1.1 and `@responsible-ai/piece-litellm-proxy` 0.1.1 installed,
  `@activepieces/piece-forms` 0.5.0 present, AI provider "LiteLLM Proxy (Responsible AI)" created
- Frontend rebuilt and uploaded (index.html, assets), CloudFront `E3SBHD9QG7B984` invalidated; the Workflow Apps tab
  appears for the `admin` group
- Verification: `tests/workflow_apps_e2e.py` against the API with a Cognito ID token (temporary admin user, deleted
  afterwards): all 23 steps pass on image `1c6425c`. Responsible AI chat app and direct LiteLLM app created, published and
  answering through the gateway (0.6 s and 0.5 s), run `SUCCEEDED`, gateway metering and proxy spend sync visible in FinOps,
  invalid app token rejected. Two demo apps from the first run left in place for inspection.
- Lesson: two gateway workers bootstrapped the fresh engine at the same moment and created duplicate AI providers; the
  bootstrap now takes a database lease and removes duplicates by name (verified on the final rollout).
- Finding: the gateway task definition passes `DATABASE_URL` (with the Aurora master password) as a plain environment
  variable (TD-33). Not changed in this deployment.

## Addendum 2026-10-03 (later) — Workflow Studio; engine without a user-facing URL

Gateway image `0aa6c16` (task definition `:10`) rolled from a reviewed plan: `ACTIVEPIECES_PUBLIC_URL` removed from the
task environment, Workflow Studio routes added. Frontend rebuilt and uploaded (`index.html`, one CSS and one JS asset),
CloudFront `E3SBHD9QG7B984` invalidated. Design: [ACTIVEPIECES_INTEGRATION.md](../ACTIVEPIECES_INTEGRATION.md) §5.3 and
[WORKFLOW_STUDIO_PLAN.md](../WORKFLOW_STUDIO_PLAN.md) (Track 2).

- Workflow Apps tab: no engine link or iframe; "Open Studio" builds, tests, publishes, inspects runs and chats inside the
  portal under the Cognito session.
- Verification with a temporary Cognito admin (deleted afterwards): `tests/workflow_studio_e2e.py` 23 of 23 and
  `tests/workflow_apps_e2e.py --cleanup` 23 of 23 against the API. Step test through the engine 1.2 s; chat 0.5 to 0.7 s.
- Pending operator action: destroy the legacy public engine API `responsible-ai-dev-workflows-api`
  (`infra/live/dev/api-gateway-workflows`, 6 resources: API, stage, two routes, integration, VPC link). The destroy plan was
  prepared; the apply is a protected action in the automated session. Until then the engine UI still answers on
  `https://kv84d4ljc6.execute-api.ap-southeast-1.amazonaws.com` with its own login; nothing in the portal references it.
- Rollout observation: for about a minute both task revisions served traffic (old revision 404 on the Studio routes);
  verify after the old task drains.

## Addendum 2026-10-05 — AWS pieces and MCP publishing

Applied from reviewed plans: `ecs-activepieces` (task role policy with Bedrock, OpenSearch and Quick actions;
task definition `:2` with `AP_SANDBOX_PROPAGATED_ENV_VARS` so piece execution reaches the task-role credentials;
`AP_ALLOWED_EMBED_ORIGINS` dropped), `api-gateway` (default-route throttling burst 100 / 50 rps), `ecs-ai-gateway`
image `13b9294` (task definition `:11`, `PUBLIC_BASE_URL` = the HTTP API endpoint). Frontend uploaded and CloudFront
`E3SBHD9QG7B984` invalidated. Design: [ACTIVEPIECES_INTEGRATION.md](../ACTIVEPIECES_INTEGRATION.md) §5.6, §5.7 and
[MCP_PUBLISHING.md](../MCP_PUBLISHING.md).

- Engine: four new piece archives installed by the gateway bootstrap (`@responsible-ai/piece-aws-bedrock-agents`,
  `-aws-bedrock-flows`, `-aws-opensearch`, `-aws-quick`, all 0.1.0).
- MCP endpoint live at `https://0nl4sfks87.execute-api.ap-southeast-1.amazonaws.com/mcp` (keys issued from the portal;
  no key left in place: the e2e key was revoked and the app deleted).
- Verification with a temporary Cognito admin (deleted afterwards): `tests/mcp_e2e.py` 19 of 19;
  `tests/aws_pieces_smoke.py` 18 of 18 (task-role connections validated, Bedrock lists empty, OpenSearch request
  signed, Quick reports the account is not subscribed). Nothing created in Bedrock, OpenSearch or Quick.
- Rollouts: engine task replaced (in-memory queue, no runs in flight), gateway rolled; both reached steady state.
- Still pending from the previous addendum: operator destroy of the legacy `api-gateway-workflows` HTTP API.

## Addendum 2026-10-05 (later) — Environment torn down

Requested in chat ("tear down the AWS deployment"). Every module under `infra/live/dev` was destroyed from a reviewed
saved plan (`terragrunt plan -destroy -out=…` → review of the `will be destroyed` list → `terragrunt apply <plan>`),
dependents first: observability (2) → frontend-s3-cloudfront (6) → api-gateway (6) → ecs-ai-gateway (16) →
cognito (8), ecs-litellm-proxy (22), ecs-activepieces (17), ecr (2) in parallel → aurora-postgres (5) → secrets (26) →
network (19). 129 resources in all. The legacy module `api-gateway-workflows` already had an empty state (its HTTP API
`kv84d4ljc6` was gone before this session) and its folder was removed from the repo (TD-30 resolved).

Done by hand around the destroys: the frontend bucket emptied (11 object versions; no `force_destroy`), the 12 images in
the ECR repository deleted (no `force_delete`), and the three Container Insights log groups
`/aws/ecs/containerinsights/responsible-ai-dev-*/performance` deleted (ECS creates them outside Terraform).
Slowest steps: Aurora cluster 9 min, LiteLLM ECS service drain 8 min, NAT gateway 3 min, CloudFront 3 min.

Verified afterwards in account 767141477889: no ECS cluster, RDS cluster, load balancer, security group, IAM role,
CloudWatch alarm, log group, HTTP API, Cognito user pool, CloudFront distribution, ECR repository or S3 bucket with the
`responsible-ai-dev` prefix remains; VPC `vpc-0f6b4c53dd9d38e19` and its NAT gateway are gone. The unrelated `cloudbox2`
workload in the same account was not touched.

What remains, on purpose:

| Item | Why | Cost |
|---|---|---|
| Manual Aurora cluster snapshot `responsible-ai-dev-aurora-final-2026-10-05` (about 1 GB) | The module sets `skip_final_snapshot = true`; the snapshot keeps the application tables, LiteLLM tables and Activepieces flows restorable. Delete it when it is no longer wanted. | cents per month |
| Eleven secrets `responsible-ai-dev/*`, scheduled for deletion | `recovery_window_in_days = 7`; they disappear on 2026-10-12 unless restored | none |
| State bucket `responsible-ai-terraform-state-dev-767141477889` and lock table `responsible-ai-terraform-locks-dev` | Empty states; a redeploy needs no new `backend bootstrap` | cents per month |

Every entry point named above (CloudFront `d12wylhj234wu3`, HTTP API `0nl4sfks87`, the Cognito domain, the internal ALBs)
no longer exists. To redeploy, follow [AWS_DEV_DEPLOYMENT_RUNBOOK.md](../AWS_DEV_DEPLOYMENT_RUNBOOK.md) from §3: the
resource names stay the same, the ids and hostnames will be new, and the secret values must be entered again.
