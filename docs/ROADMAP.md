# Roadmap — Responsible AI Enterprise Gateway

Two-week sprints. Sprint 1 is implemented in this repository; later sprints are proposals to be confirmed at each planning session. Design context is in [ARCHITECTURE_DESIGN.md](ARCHITECTURE_DESIGN.md); the debt each sprint retires is in [TECH_DEBT.md](TECH_DEBT.md).

## Themes

| Theme | Outcome we are buying |
|---|---|
| **Model gateway** | Every model call is governed, metered and portable across providers. |
| **FinOps** | Spend is visible per tenant/user/purpose, budgeted, and controllable without releases. |
| **AIOps** | The LLM path has SLIs, alarms, dependency checks and runbooks. |
| **Responsible-AI evaluation** | Ragas/TruLens become a sampled evaluation platform with datasets and trends, not inline per-request calls. |
| **Governance & compliance** | Policies, audits and reports are tenant-aware, retained, exportable and reviewable. |
| **Scale & platform** | The gateway serves hundreds of concurrent users and other applications in the organisation. |
| **Platform integration & guided configuration** | The AI App control plane discovers the gateway at run time and receives gateway-issued credentials; administrators configure every scope with examples, validation and AI assistance. See [PROXY_MANAGER_ENTERPRISE_DESIGN.md](PROXY_MANAGER_ENTERPRISE_DESIGN.md). |
| **Multi-tenancy** | Tenants get separated data, configuration, credentials, budgets and policies, with a choice of isolation tier. See [MULTI_TENANCY_DESIGN.md](MULTI_TENANCY_DESIGN.md). |

## Sprint plan

### Sprint 1 — LiteLLM forward proxy, metering, FinOps & AIOps v1  ✅ implemented 2026-10-02

- Single egress client (`app.llm_client`) → LiteLLM proxy; `groq_client.py` removed; TruLens/Ragas judges routed through the proxy.
- `llm_usage_events` metering (tokens, cost, latency, retries, fallbacks, attribution).
- `GET /reports/finops`, `GET /reports/aiops`, `GET /gateway/health`, `GET /gateway/models`; `finops` / `aiops` roles.
- FinOps and AIOps dashboards; per-message usage footer; proxy-driven model selector.
- `docker-compose.yml` (Jaeger, Postgres, LiteLLM), `litellm/config.yaml` with model groups and fallbacks, offline mock mode.
- Terraform: `ecs-litellm-proxy` module; `ecs-ai-gateway` wired for proxy mode; secrets and deploy order updated.
- Tests: unit tests for the client and aggregations; `LITELLM-*`, `GATEWAY-01`, `FINOPS-01`, `AIOPS-01` scenarios.

**Exit criteria met**: no provider key needed by the application in proxy mode; cost metered from the proxy on every call; dashboards populated from live data; infra validates.

### Sprint 2 — Proxy in AWS, budgets, hardening

> Progress 2026-10-02: the proxy and keyless gateway are live in dev (account 767141477889); the gateway still uses the master key (TD-25). Remaining items below.

- Apply `ecs-litellm-proxy` in dev; move the Groq key out of the gateway task; issue the gateway a virtual key with `max_budget` and model scope.
- ✅ Proxy Manager: teams and virtual keys with budgets/RPM/TPM from the admin UI (`/team/new`, `/key/generate`), provider credentials in LiteLLM's store, MCP servers, proxy guardrails, config/spend views. Remaining: map Cognito `custom:tenant_id` → LiteLLM team automatically in the gateway.
- ✅ Multi-provider model catalogue in the admin screen (LiteLLM `/model/*`, `store_model_in_db`); Bedrock via the proxy task role (no key). Remaining: promote evaluated models to `config.yaml` and define fallbacks across providers.
- **Provider credentials in AWS Secrets Manager** (requested 2026-10-02): LiteLLM `general_settings.key_management_system: aws_secret_manager` (read-only access mode) on the proxy; Proxy Manager gets a **Store in AWS Secrets Manager** action (gateway task role `PutSecretValue` scoped to `responsible-ai-<env>/*_api_key`), keeps "Store in proxy (LiteLLM DB)" as an explicit secondary option, shows credential provenance on each provider card (Secrets Manager name / LiteLLM DB / env), and hides the key field for deployment-managed providers unless "replace" is chosen. Verify LiteLLM's secret-name resolution (variable name vs. prefix) during implementation. Other secret managers (HashiCorp Vault, Azure Key Vault, GCP Secret Manager) use the same `key_management_system` setting, one per proxy instance.
- **Tenant → LiteLLM team mapping**: the gateway calls the proxy with the tenant's team virtual key so team budgets, limits and model scope are enforced per tenant; team-scoped models ([MULTI_TENANCY_DESIGN.md](MULTI_TENANCY_DESIGN.md) §4.1).
- Langfuse callback on the proxy; remove app-side decorators (TD-11).
- CloudWatch EMF metrics from the gateway (latency, errors, cost) and alarms on p95 / error rate / budget burn; SNS notifications.
- Separate Postgres database/schema and credentials for LiteLLM (TD-13); Alembic migrations for the app schema (TD-04).
- Reconciliation job: gateway `llm_usage_events` vs LiteLLM `LiteLLM_SpendLogs`, daily, with drift alert.
- Load test: 200 concurrent chat sessions through API Gateway → gateway → proxy; record p95 and proxy overhead.

**Exit criteria**: `/gateway/health` in dev shows `application_holds_provider_key: false`; a tenant hitting its budget gets a 429 from the proxy surfaced as `HTTP_429` in AIOps; alarms fire in a game day.

### Sprint 3 — Evaluation platform (Ragas, TruLens)

- Move judge calls off the request path: sample N % of framework-mode responses into an evaluation queue (SQS) processed by an ECS task; keep an inline option for demos (TD-03).
- Ragas: `evaluate()` over golden datasets (fairness, faithfulness, answer relevance) stored in S3; nightly runs; trend per model and per judge model.
- TruLens: `TruApp` sessions with feedback functions persisted to Postgres; link TruLens record ids to `request_id`.
- Evaluation budget as a FinOps line (purpose `judge_*` already separated); judge-model A/B (`judge-fast` vs chat model) with agreement metrics.
- Evaluation dashboard v2: per-model, per-judge, per-tenant trends; regression alerts when a score drops below a threshold after a model/prompt change.
- Replace static placeholder pillars (verifiability, transparency, governance, controllability in framework mode) with real signals (TD-09).
- ✅ **Proxy Manager completeness** (requested 2026-10-02): every section can define and edit — router settings, LiteLLM settings, callbacks with env vars, Redis cache form/test/ping/flush, general settings form, model edit (prices/params/alias), key/team edit and key regeneration, MCP edit, guardrail toggle/test, chat allowlist. Enabled by making `litellm/config.yaml` bootstrap-only with DB-managed runtime settings seeded from `litellm_runtime_defaults.json`. Session refresh for Cognito tokens.
- **Admin audit view**: expose `policy_audit_events` (provider/model/key/settings changes, rotations, seeding) as a Proxy Manager section; today the rows are written but only readable in the database.
- **Capability discovery for the Proxy Manager** (requested 2026-10-02): capability manifest from LiteLLM `/routes` + `/openapi.json` with coverage status on the Overview, upgrade diff + audit event, admin-enabled dynamic allow-list (`litellm.allowed_routes_extra`, inference routes always excluded), schema-driven explorer for allowed-but-uncurated routes, provider registry sourced from `/public/providers/fields`, proxy image pinned to a release tag ([LITELLM_PROXY_MANAGER.md](LITELLM_PROXY_MANAGER.md) "Capability discovery").
- **Settings hierarchy phase 1** (requested 2026-10-02, [PROXY_MANAGER_ENTERPRISE_DESIGN.md](PROXY_MANAGER_ENTERPRISE_DESIGN.md) §1): tenant / department / application registry mapped to LiteLLM organization / team / virtual key; scoped `gateway_settings` with narrow-only inheritance and locks; scope switcher in the Proxy Manager with "inherited from" and override/revert; team- and key-level `router_settings`, guardrails, tags and callbacks; `tenant-admin` and `department-admin` roles. Single-tenant deployments use the same tree under `default`.
- **Guided configuration phase 1** (§3): settings catalogue with recommended values per environment and workload served by the gateway, inline help and "Recommended" chips, server-side validation before save (`/gateway/admin/litellm-config/validate`), configuration profiles (Starter, Production cost-optimised, Production latency-optimised, Regulated, Agentic) with diff preview.
- **Per-tenant configuration**: `gateway_settings` tenant namespace (default/judge model, enablement, credential store, cache namespace, isolation tier), tenant selector in the Proxy Manager, `tenant-admin` role; mixed credential stores in one proxy (one tenant on LiteLLM DB, another on Secrets Manager).

**Exit criteria**: framework-mode p95 drops below the code-mode p95 + 1 s; evaluation coverage and spend reported separately.

### Sprint 4 — Governance, compliance and RBAC

- Tenant-aware policies: policy ownership and activation per tenant; tenant filter on all reports.
- **AI App control plane integration** (requested 2026-10-02, [PROXY_MANAGER_ENTERPRISE_DESIGN.md](PROXY_MANAGER_ENTERPRISE_DESIGN.md) §2): `/.well-known/ai-gateway` discovery document and authenticated capability manifest with JSON Schemas; tenant and application onboarding APIs that create the LiteLLM organization/team/key and an OAuth2 client (client-credentials, resource-server scopes) with build-time and run-time credentials and auto-rotation; gateway token exchange (`/oauth2/exchange`, KMS-signed) for the App platform acting for a tenant; webhooks/EventBridge events; enforcement at network, token/registry and key layers so no tenant or third-party app is served without a gateway grant.
- Policy-as-code export/import (YAML) with signed approvals; policy change audit report.
- Audit retention and deletion jobs aligned to `audit_retention_days`; PII-free guarantee tests on audit/metering tables.
- Prompt/response redaction before any trace export (Presidio on the proxy path via LiteLLM guardrail hook or pre-callback).
- Harden admin endpoints: authenticate `/audit`, `/policy`, `/policies/test` (TD-08); move Guardrails Hub installs from the API to the image build (TD-19).
- Compliance exports: monthly CSV/Parquet of audits, violations and spend to S3 for finance and risk.
- **Tenant data separation**: `tenant_id` on all tenant-owned tables with Postgres row-level security; tenant-scoped policies, proxy guardrails and MCP access groups per team; tenant-scoped reports and exports (isolation tier T1 complete).

**Exit criteria**: every report endpoint is tenant-scoped and role-gated; a quarterly compliance export runs unattended.

### Sprint 5 — Scale, resilience and user experience

- ECS autoscaling on request count and p95 for both services; proxy ALB ingress by security group (TD-13).
- **Response caching with ElastiCache** ([RESPONSE_CACHING.md](RESPONSE_CACHING.md)): `elasticache-redis` Terraform module (Serverless Valkey/Redis, TLS, AUTH token in Secrets Manager, SG from the proxy only), `REDIS_*` on the proxy, caching pinned in `litellm/config.yaml` for prod or configured at runtime from the Proxy Manager Cache panel (`POST /cache/settings`, test, ping, flush), per-tenant cache namespaces, `cache_hit` in usage metering and a cache-hit-rate tile on FinOps.
- **Configuration copilot** (requested 2026-10-02, [PROXY_MANAGER_ENTERPRISE_DESIGN.md](PROXY_MANAGER_ENTERPRISE_DESIGN.md) §3.4): "Ask the gateway" panel grounded in the settings catalogue, version-matched LiteLLM docs, the effective configuration of the selected scope and FinOps/AIOps signals; explains, recommends, diagnoses and proposes changes as reviewable diffs (propose-only, scope-bound, audited, evaluated with Ragas); proactive insights on the Overview.
- **T2 dedicated proxy** module for tenants that need their own LiteLLM instance, database and secret manager (Vault / Key Vault / GCP).
- Streaming responses end-to-end (SSE) with guardrail output checks on the streamed buffer.
- Circuit breaker and provider health routing (`cooldown_time`, `allowed_fails`) tuned from load tests; multi-region readiness review.
- Frontend: router, per-screen lazy loading, accessible charts, shared chart library consolidation (TD-10, TD-18).

**Exit criteria**: 500 concurrent users sustained in load test with p95 within SLO; cache-hit and fallback rates visible.

### Sprint 6 — Platformisation and chargeback

- Offer the LiteLLM proxy as the organisation's model gateway: self-service team keys, model catalogue, per-team dashboards.
- Showback/chargeback: export spend by tenant/team to AWS Cost and Usage Report via cost allocation tags; FinOps anomaly detection (daily spend deviation); per-tenant chargeback reconciled with LiteLLM `/global/spend/report?group_by=team`.
- Optional **T3 dedicated-account** deployment pattern (Terragrunt live folder per tenant account).
- Agent/MCP governance: tool-call policies and metering for agentic workloads; `agent_id` becomes a first-class budget dimension.
- Model lifecycle: deprecation schedule per model group; canary routing for new models with evaluation gates from Sprint 3.

**Exit criteria**: a second application onboards to the proxy with its own key and budget without changes to this repository.

## Milestones

| Milestone | Target | Depends on |
|---|---|---|
| M1 Proxy mandatory locally | Sprint 1 ✅ | — |
| M2 Proxy live in dev AWS, gateway keyless | Sprint 2 ✅ 2026-10-02 (scoped key pending, TD-25) | — |
| M3 Budgets enforced per tenant | Sprint 2 | M2 |
| M4 Evaluation off the request path | Sprint 3 | M2 |
| M5 Tenant-scoped governance and exports | Sprint 4 | M3 |
| M6 500-user load test within SLO | Sprint 5 | M2, M4 |
| M7 Second application onboarded | Sprint 6 | M3, M5 |
| M8 Provider credentials in AWS Secrets Manager (plus LiteLLM DB as explicit option) | Sprint 2 | M2 |
| M9 Tenants enforced via LiteLLM teams; per-tenant settings and credential store | Sprints 2–3 | M8 |
| M10 Tenant data separation (RLS, tenant-scoped policies/guardrails/MCP/reports) — isolation tier T1 | Sprint 4 | M9 |
| M11 Response caching on ElastiCache with per-tenant namespaces | Sprint 5 | M2 |
| M12 Dedicated-proxy tier (T2) available | Sprint 5 | M10 |
| M13 Settings hierarchy GA (tenant → department → application, inheritance, scope switcher) | Sprint 3 | M9 |
| M14 AI App control plane integrated: discovery document, capability manifest, gateway-issued credentials, token exchange, events | Sprint 4 | M13 |
| M15 Guided configuration: catalogue, validation, profiles (Sprint 3) and copilot (Sprint 5) | Sprints 3, 5 | M13, M4 |

## Success metrics

| KPI | Baseline (2026-10-02, local) | Target |
|---|---|---|
| Model calls through the proxy | 100 % (proxy mode) | 100 % in all environments |
| Provider keys in application tier | 0 in proxy mode (dev `.env` still carries one) | 0 everywhere |
| Cost attributed to tenant/purpose | 100 % of metered calls | 100 %, reconciled daily with LiteLLM |
| Judge share of spend | 52 % | < 20 % after sampling + `judge-fast` |
| Framework-mode p95 | ~20 s (inline judges) | < code-mode p95 + 1 s |
| Fallback rate | 1 of 19 (chaos test) | < 1 % in production |
| Time to add a provider/model | code change + release | config change + proxy redeploy |
