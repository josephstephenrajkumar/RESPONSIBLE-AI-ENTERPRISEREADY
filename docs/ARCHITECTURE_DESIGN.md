# Architecture Design Document — Responsible AI Enterprise Gateway

| | |
|---|---|
| Status | Sprint 1 implemented and deployed to dev (account 767141477889, 2026-10-02); Sprints 2+ are proposals (see [ROADMAP.md](ROADMAP.md)) |
| Date | 2026-10-02 |
| Owners | Platform / AI Gateway team |
| Related | [ARCHITECTURE_BLUEPRINT.md](ARCHITECTURE_BLUEPRINT.md) (v1 shape), [AWS_SERVICE_MAPPING.md](AWS_SERVICE_MAPPING.md), [TECH_DEBT.md](TECH_DEBT.md), [RESPONSIBLE_AI_DESIGN.md](RESPONSIBLE_AI_DESIGN.md) |

## 1. Purpose and scope

This document reviews the current Responsible AI Enterprise Gateway, states the design requirements it must now meet, and defines the target architecture that introduces:

1. a **LiteLLM proxy as the mandatory forward proxy** for every model call (Sprint 1, implemented);
2. a **FinOps dashboard** for administrators (Sprint 1, implemented);
3. an **AIOps dashboard** for operators (Sprint 1, implemented);
4. the path for the remaining responsible-AI capabilities (Ragas, TruLens, governance) to mature into platform services (Sprints 2–6, see roadmap).

It covers the application (FastAPI gateway, React frontend), the model gateway (LiteLLM), the AWS deployment (Terragrunt/Terraform), data, security and observability. It does not re-specify the responsible-AI pillar logic, which remains documented in [RESPONSIBLE_AI_DESIGN.md](RESPONSIBLE_AI_DESIGN.md).

## 2. Current-state review (as-is, before Sprint 1)

### 2.1 What exists

```text
React/Vite  ->  FastAPI "AI Gateway"  ->  Groq (direct HTTPS, GROQ_API_KEY in the app)
                   |-- Presidio privacy (in/out)        framework mode
                   |-- Guardrails AI safety (in/out)    framework mode, DB-backed policies
                   |-- Ragas fairness judge             framework mode, LLM call via Groq
                   |-- TruLens explainability judge     framework mode, LLM call via Groq
                   |-- code-mode heuristics             code mode
                   |-- SQLAlchemy audit / violations / policies (SQLite dev, Aurora prod)
                   |-- OpenTelemetry -> Jaeger / ADOT -> X-Ray
                   `-- Langfuse decorators (optional)
```

The AWS footprint (Terragrunt) is complete for v1: VPC, Cognito, Aurora Serverless v2, ECR, ECS Fargate behind an internal ALB, API Gateway HTTP API with a VPC link, S3 + CloudFront, Secrets Manager, CloudWatch alarms. A dev deployment snapshot exists (`docs/aws-snapshots/`).

### 2.2 Strengths worth preserving

- The **inline policy-enforcement gateway** pattern is right for interactive chat: no brokers, no polling, responsible-AI wraps the pipe.
- Policy governance is real: lifecycle (`draft → approved → active`), hashed runtime decisions, violation records, validator health surfaced to the UI, auto-disable of unloadable validators.
- Framework integrations are genuine (Presidio, Guardrails, Ragas, TruLens), with honest fallbacks and an integration scenario suite that reports `DEGRADED` rather than hiding fallback.
- Infrastructure is modular and reproducible; the backend image is non-root and production-shaped.

### 2.3 Gaps found in the review

| # | Finding | Consequence |
|---|---|---|
| G1 | Provider credential (`GROQ_API_KEY`) lives in the application tier and is referenced from three places (`groq_client.py`, `trulens_eval.py` direct `httpx.post`, `ragas_eval.py` indirectly). | Credential sprawl; no single egress; no provider portability. |
| G2 | No cost metering anywhere. Token usage is captured only inside a Langfuse observation. | No FinOps visibility; no budgets; no unit economics. |
| G3 | No latency/error/retry telemetry beyond raw traces. Dashboards cover responsible-AI outcomes only. | No AIOps view; incidents are diagnosed from Jaeger by hand. |
| G4 | No retries, fallbacks or circuit breaking on the provider call. | A Groq incident is a chat outage. |
| G5 | Three LLM calls per framework-mode chat (answer + two judges) made inline. | ~20 s p95 per framework request in testing; evaluation spend is roughly half of total spend. |
| G6 | Model is a free-text field in the UI and a hardcoded default in the schema. | Any model string reaches the provider; no allowlist. |
| G7 | README references `docker compose`, but no compose file exists; Jaeger must be started by hand. | Onboarding friction; no reproducible local stack. |
| G8 | Admin RBAC has one role (`policy-manager`). | Cost and operations data would be visible to policy authors, or to nobody. |
| G9 | Several deferred items from the blueprint are still open: Alembic, rate limiting, tenant-aware policies, audit retention. | Tracked in [TECH_DEBT.md](TECH_DEBT.md). |

## 3. Design requirements

### 3.1 Functional

| ID | Requirement | Sprint |
|---|---|---|
| F1 | All model calls from the application (chat and judges) go through one LLM egress client that targets the LiteLLM proxy. No code path may call a provider directly in `proxy` mode. | 1 |
| F2 | Each model call is metered: tokens, cost (from the proxy), latency, retries, fallbacks, status, served model, and attributed to user, tenant, client, agent, session and purpose. | 1 |
| F3 | Administrators with the `finops` role see spend totals, trends, breakdown by model / tenant / user / purpose / client, unit economics and budget posture. | 1 |
| F4 | Operators with the `aiops` role see availability, latency percentiles, error classes, retries/fallbacks, per-model health and live dependency checks (proxy, DB, tracing, validators). | 1 |
| F5 | Chat responses expose per-message usage (model served, tokens, cost, latency) for transparency. | 1 |
| F6 | Model selection is constrained to what the proxy serves, optionally narrowed by a gateway allowlist. | 1 |
| F7 | The proxy is deployable on AWS alongside the gateway with Terragrunt, holding provider keys that the gateway task never receives. | 1 (module), 2 (apply + hardening) |
| F8 | Per-tenant/team virtual keys, budgets and rate limits are enforced at the proxy. | 2 |
| F9 | Responsible-AI evaluation (Ragas/TruLens) runs as a sampled/asynchronous evaluation pipeline with its own budget, not inline on every request. | 3 |

### 3.2 Non-functional

| ID | Requirement |
|---|---|
| N1 | Added latency from the proxy ≤ 100 ms p95 (measured 56–94 ms overhead on the mock upstream; LiteLLM reports it in `x-litellm-overhead-duration-ms`). |
| N2 | Metering must never fail a chat: persistence errors are swallowed and logged, not raised. |
| N3 | No silent bypass: if the proxy is unreachable the request fails with provider `litellm-error`; direct provider access is only available by explicit configuration (`LLM_GATEWAY_MODE=direct`). |
| N4 | Secrets: provider keys only in the proxy task; the gateway holds a LiteLLM virtual key scoped to the models and budget it needs. |
| N5 | Observability: gateway and proxy export OpenTelemetry to the same collector with trace propagation. |
| N6 | Multi-provider: adding a provider or model is a `litellm/config.yaml` change plus redeploy of the proxy, not an application release. |
| N7 | Dashboards are read-only views over persisted data; they add no new write paths beyond the metering table. |

## 4. Target architecture

### 4.1 Logical view: two gateways with distinct responsibilities

```text
                 ┌──────────────────────────────────────────────────────────────┐
                 │  Policy Enforcement Gateway  (FastAPI, this repo)             │
 Chat client ───▶│  authn/z (Cognito) · privacy (Presidio) · safety (Guardrails) │
   React         │  evaluation hooks (Ragas/TruLens) · audit · metering · RBAC   │
                 │                      app.llm_client  (single egress)          │
                 └──────────────────────────────┬───────────────────────────────┘
                                                │ OpenAI-compatible API + virtual key
                                                │ user, metadata.tags = tenant/client/agent/purpose
                 ┌──────────────────────────────▼───────────────────────────────┐
                 │  Model Gateway  (LiteLLM proxy)                               │
                 │  provider credentials · model groups · routing · retries      │
                 │  fallbacks · budgets / rate limits · spend log · cost headers │
                 │  OTel + Langfuse callbacks                                    │
                 └───────┬──────────────────┬──────────────────┬────────────────┘
                         ▼                  ▼                  ▼
                       Groq            Amazon Bedrock       OpenAI / others
```

The split is deliberate. The policy gateway knows about users, tenants, policies and pillars; the model gateway knows about providers, keys, prices and routing. Neither needs the other's concerns, and the model gateway can later serve other applications in the organisation (roadmap, Sprint 6).

### 4.2 Request flow (framework mode)

```text
1  POST /chat (JWT)                      gateway resolves model, checks allowlist,
                                         binds request context {request_id, user, tenant,
                                         client, agent, session, mode} for metering
2  Presidio input redaction
3  Guardrails input validation           blocked -> answer without any model call
4  llm_client.chat()  ───────────────▶   LiteLLM /chat/completions
                                           ├─ route model group -> deployment
                                           ├─ retries (2) / fallback chain
                                           └─ provider call
   ◀────────────────────────────────────  body: choices, usage, model
                                          headers: x-litellm-response-cost, -call-id,
                                          -attempted-retries, -attempted-fallbacks,
                                          -overhead-duration-ms, -model-api-base
5  metering row (purpose=chat)           llm_usage_events
6  Presidio / Guardrails output checks
7  Ragas judge  ─▶ LiteLLM (judge model) metering row (purpose=judge_fairness)
8  TruLens judge ─▶ LiteLLM (judge model) metering row (purpose=judge_explainability)
9  audit event + violation records       audit_events, guardrail_violations
10 ChatResponse.metadata.usage           transparency footer in the UI
```

Code mode skips 2, 3, 6, 7, 8 and uses local heuristics; it still goes through step 4 and 5.

### 4.3 Deployment view (AWS)

```text
CloudFront ─ S3 (React)
React ─ API Gateway HTTP API ─ VPC link ─ internal ALB ─ ECS Fargate: ai-gateway (+ ADOT sidecar)
                                                             │
                                                             ▼ http://<internal ALB>  (LITELLM_PROXY_URL)
                                                 internal ALB ─ ECS Fargate: litellm-proxy (+ ADOT sidecar)
                                                             │        ▲ config.yaml from private S3 bucket
                                                             │        ▲ LITELLM_MASTER_KEY, GROQ_API_KEY from Secrets Manager
                                                             ▼
                                                   NAT ─ Groq / Bedrock (IAM task role) / OpenAI
ai-gateway, litellm-proxy ─ Aurora PostgreSQL (app schema; LiteLLM_* tables)
ai-gateway, litellm-proxy ─ CloudWatch Logs / X-Ray via ADOT
```

Terragrunt order: `network → secrets → cognito → aurora-postgres → ecr → (image push) → ecs-litellm-proxy → ecs-ai-gateway → api-gateway → frontend-s3-cloudfront → observability`. New module: [`infra/modules/ecs-litellm-proxy`](../infra/modules/ecs-litellm-proxy/README.md). The `ecs-ai-gateway` module now takes `llm_gateway_mode`, `litellm_proxy_url`, `litellm_api_key_secret_arn`, `llm_default_model`, `llm_judge_model`, `llm_allowed_models`, `finops_monthly_budget_usd`, and mounts `GROQ_API_KEY` only in `direct` mode.

### 4.4 Data view

New table `llm_usage_events` (one row per model call; several per chat request, joined on `request_id`):

| Column group | Columns |
|---|---|
| Identity | `request_id`, `call_id` (LiteLLM), `timestamp` |
| Attribution | `user_id`, `user_email`, `tenant_id`, `client_id`, `agent_id`, `session_id`, `mode`, `purpose` (`chat`, `judge_fairness`, `judge_explainability`) |
| Routing | `requested_model`, `served_model`, `provider`, `gateway_mode`, `api_base` |
| FinOps | `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`, `cost_source` (`litellm` / `estimated` / `unknown` / `none`) |
| AIOps | `latency_ms`, `proxy_overhead_ms`, `retries`, `fallbacks`, `status` (`success` / `error` / `unconfigured`), `error_type`, `http_status` |

Existing tables are unchanged. LiteLLM keeps its own spend log (`LiteLLM_SpendLogs`) in Postgres; the gateway table is the system of record for the dashboards because it carries tenant/purpose attribution and blocked/judge context, while LiteLLM's log is the reconciliation source (Sprint 2 adds the reconciliation job).

### 4.5 Security view

- **Credential boundary**: provider keys exist only in the proxy task (`secrets` → `ecs-litellm-proxy`). The gateway task receives a LiteLLM **virtual key** (`litellm_gateway_key`) generated with `/key/generate`, scoped to the model groups it uses and a monthly budget. The AIOps dashboard flags if `GROQ_API_KEY` is still present in the gateway environment.
- **Network**: both ALBs are internal; the proxy ALB accepts traffic only from the VPC CIDR (tighten to the gateway security group in Sprint 2, see TD-13).
- **Authz**: new Cognito groups `finops` and `aiops` (plus `admin`) gate `/reports/finops` and `/reports/aiops`; `policy-manager` keeps the responsible-AI dashboards. `/auth/me` returns `view_finops` / `view_aiops` so the UI only shows permitted tabs.
- **Egress control**: `LLM_ALLOWED_MODELS` at the gateway and `models` on the virtual key at the proxy give defence in depth against arbitrary model strings.
- **Data minimisation**: metering rows store no prompt or completion text. Prompts reach the proxy only as the request body; configure Langfuse on the proxy with redaction if traces must not contain content.

### 4.6 Observability view

- Gateway spans: `chat.request` → `llm_gateway_call` carries `llm.gateway_mode`, `llm.status`, `llm.total_tokens`, `llm.cost_usd`, `llm.latency_ms`, `llm.call_id`.
- Proxy spans via the LiteLLM `otel` callback to the same collector (`litellm-proxy` service in Jaeger locally, X-Ray in AWS).
- Metrics: the AIOps report derives availability, p50/p95/p99, error classes and fallback counts from `llm_usage_events`; CloudWatch alarms on proxy ALB 5xx and unhealthy hosts are in the module. Sprint 2 adds CloudWatch EMF metrics from the gateway so alarms can be set on p95 and error rate.

### 4.7 Model catalogue (multi-provider)

Administrators manage providers and models from the Configuration screen; the gateway wraps LiteLLM's model
management API and adds a fixed provider registry, enablement driven by the credentials the proxy holds, explicit
model enablement, metered test calls and audit events. Bedrock models need no key (proxy task role). Details,
endpoints and the enable-a-provider procedure are in [MODEL_CATALOG.md](MODEL_CATALOG.md).

### 4.8 Proxy Manager (LiteLLM administration)

Administrators manage the model gateway from the **Proxy Manager** tab: providers (enable/disable, credentials),
models (catalogue, default/judge), teams and virtual keys with budgets, MCP servers, proxy-side guardrails, routing
and spend. The gateway exposes a governed passthrough (`/gateway/admin/litellm/*`, allow-listed, audited) plus
curated endpoints and a `gateway_settings` table for runtime overrides. Details in
[LITELLM_PROXY_MANAGER.md](LITELLM_PROXY_MANAGER.md).

## 5. Key design decisions

| ADR | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| ADR-01 | Use **LiteLLM proxy** as a forward proxy in front of all providers. | Direct SDK per provider; API Gateway + Lambda router; Bedrock-only. | OpenAI-compatible surface the app already speaks; multi-provider; keys, budgets, retries, fallbacks, spend log and cost headers out of the box; self-hostable on ECS. |
| ADR-02 | **One egress client** (`app.llm_client`) replaces `groq_client.py` and the direct `httpx` call in `trulens_eval.py`. | Keep per-framework adapters calling the provider. | Enforces F1; one place to meter, trace and fail safely. |
| ADR-03 | **No silent fallback to direct provider access.** Proxy failure returns `litellm-error`; `direct` is an explicit mode. | Fall back to Groq when the proxy is down. | A silent bypass would hide outages, skip budgets and leak the credential boundary. |
| ADR-04 | The **gateway records its own metering** from response headers/body; LiteLLM's spend log is a reconciliation source. | Query LiteLLM `/spend/logs` for dashboards. | Attribution (tenant, purpose, blocked) only exists in the gateway; dashboards work even when the proxy DB is down; no coupling to LiteLLM's schema. |
| ADR-05 | **Judge calls use a separate, configurable model** (`LLM_JUDGE_MODEL`, default = chat model; `judge-fast` group recommended). | Always use the chat model. | Evaluation was ~50 % of spend; a cheaper judge halves cost without touching chat quality. Default preserves current behaviour. |
| ADR-06 | **Model groups** (`chat-default`, `judge-fast`) in the proxy; the app may target capabilities, not vendors. | Vendor model names only. | Routing and cost optimisation become proxy config changes. |
| ADR-07 | **Langfuse at the proxy**, not the app, is the recommended configuration. | Keep app-side decorators. | One generation record per call; app decorators retained but documented as duplicate when both are set (TD-11). |
| ADR-08 | Proxy config distributed via **S3 object** loaded at task start. | Bake into image; Parameter Store. | Terraform-managed, diffable, no image rebuild; LiteLLM supports it natively. |
| ADR-09 | **Postgres for LiteLLM** (dev: shared Aurora database; prod: separate DB/schema). | Run proxy stateless. | Virtual keys, team budgets and spend log need persistence. |
| ADR-10 | Dashboard aggregation in the gateway over a bounded window (Python over ≤ 20 k rows). | Materialised views; CloudWatch Metrics. | Fast to ship, adequate for dev volumes; replaced by rollups/EMF in Sprint 2 (TD-07). |
| ADR-13 | **Proxy Manager = governed passthrough + runtime settings.** One allow-listed gateway route forwards LiteLLM management calls with the admin key, audits writes with redaction; provider/model enablement and default/judge models live in a DB-backed `gateway_settings` table. Provider keys are stored in LiteLLM's encrypted credential store, never in the app. | Expose LiteLLM's own admin UI; rebuild every LiteLLM screen; keep enablement in Terraform. | Admins get the full LiteLLM capability set (keys, teams, MCP, guardrails, config, spend) behind Cognito RBAC without a second login or exposing the proxy; inference routes stay excluded so metering/policy cannot be bypassed. See [LITELLM_PROXY_MANAGER.md](LITELLM_PROXY_MANAGER.md). |
| ADR-12 | **Admin model catalogue over LiteLLM's model-management API** (`/model/info`, `/model/new`, `/model/delete`, price map) with `store_model_in_db: true`; explicit models per enabled provider, no wildcard routes; new models reference `os.environ/<KEY>`. | Wildcard provider routes; editing `config.yaml` for every model; storing provider keys in the app. | Lets operators onboard any provider/model (Groq, Bedrock via IAM, Anthropic, OpenAI…) without an app release while keeping the credential boundary, the allowlist and budgets intact. See [MODEL_CATALOG.md](MODEL_CATALOG.md). |
| ADR-11 | Offline **mock upstream + `config.mock.yaml`** for zero-spend verification and CI. | Test only against Groq. | Keeps CI deterministic and free; proves routing, headers, retries and fallbacks. |

## 6. FinOps design

**Metrics**: total spend, model calls, tokens (in/out/total), average cost per call, cost per 1k tokens, judge share of cost, failed calls; breakdown by model, purpose, tenant, user (top 10), client; daily series; cost-source mix (`litellm` vs `estimated`).

**Budget model**: `FINOPS_MONTHLY_BUDGET_USD` on the gateway drives a calendar-month gauge (MTD, straight-line projection, `ok / warning (projected ≥ 80 %) / over`). Hard enforcement belongs to the proxy: virtual key `max_budget` + `budget_duration`, team budgets and per-key RPM/TPM (Sprint 2).

**Controls available to the FinOps owner** (no application release required): change `LLM_JUDGE_MODEL` to `judge-fast`; edit model groups / fallbacks in `litellm/config.yaml`; set key budgets; enable LiteLLM caching (Sprint 5).

**Dashboard**: `frontend/src/components/FinOpsDashboard.jsx` over `GET /reports/finops?days=7|30|90`, visible to `admin` and `finops`.

## 7. AIOps design

**SLIs**: availability (`success / total` model calls), p50/p95/p99 latency, error rate by class (`Timeout`, `HTTP_429`, `HTTP_5xx`, `ConnectError`), retries, fallbacks, proxy overhead, requests/hour, guardrail block rate.

**SLO targets (dev)**: availability ≥ 99 %; p95 ≤ 8 s for code mode (provider-bound); fallbacks < 1 % of calls.

**Dependency checks (live, on each report)**: LiteLLM reachability, latency, model count and whether the default model is served; tracing status; database `SELECT 1`; Guardrails validator health and active policy version; Langfuse configured; credential-boundary check.

**Alarms (Terraform)**: proxy ALB target 5xx (> 10 / 5 min), unhealthy hosts; existing ECS CPU and log-error alarms on the gateway. Sprint 2 adds EMF metrics and alarms for p95 and error rate.

**Dashboard**: `frontend/src/components/AIOpsDashboard.jsx` over `GET /reports/aiops?hours=1|24|168`, auto-refreshing, visible to `admin` and `aiops`.

## 8. API changes

| Endpoint | Change |
|---|---|
| `POST /chat` | `model` defaults to the gateway default; allowlist enforced (400). `metadata.usage` added: `gateway, served_model, prompt_tokens, completion_tokens, total_tokens, cost_usd, cost_source, latency_ms, proxy_overhead_ms, retries, fallbacks, status, error_type`. `metadata.provider` is `litellm`, `litellm-error`, `litellm-fallback` or `guardrails-policy`. |
| `GET /gateway/health` | New. Live proxy check and configuration summary. |
| `GET /gateway/models` | New. Models served by the proxy, filtered by the allowlist; `by_provider` grouping for the chat selector. |
| `GET /gateway/catalog`, `GET /gateway/catalog/providers/{p}/available`, `POST /gateway/catalog/models`, `POST /gateway/catalog/models/{name}/test`, `DELETE /gateway/catalog/models/{id}` | New. Admin model catalogue over LiteLLM `/model/*` (roles `admin`, `model-admin`; browse for `policy-manager`). |
| `POST /gateway/catalog/providers/{p}/enable|disable`, `POST/DELETE /gateway/catalog/providers/{p}/credential`, `POST /gateway/catalog/models/{name}/enable|disable`, `GET/PUT /gateway/settings`, `GET /gateway/admin/overview`, `ANY /gateway/admin/litellm/{path}` | New. Proxy Manager: runtime enablement, credentials in LiteLLM's store, default/judge overrides, governed passthrough to LiteLLM management routes. |
| `GET /reports/finops?days=` | New. Requires `finops` or `admin`. |
| `GET /reports/aiops?hours=` | New. Requires `aiops` or `admin`. |
| `GET /policy` | `model` / `provider` now reflect live gateway settings; `llm_gateway` block added. |
| `GET /auth/me` | `permissions.view_finops`, `permissions.view_aiops` added. |

## 9. Configuration

| Variable | Default | Notes |
|---|---|---|
| `LLM_GATEWAY_MODE` | `proxy` | `direct` is break-glass only. |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | Internal ALB URL in AWS. |
| `LITELLM_API_KEY` | — | Virtual key (AWS) or master key (local). |
| `LLM_DEFAULT_MODEL` | `GROQ_MODEL` or `llama-3.3-70b-versatile` | Must exist in the proxy `model_list`. |
| `LLM_JUDGE_MODEL` | = default model | `judge-fast` recommended. |
| `LLM_ALLOWED_MODELS` | empty | Comma-separated allowlist. |
| `LLM_PROVIDERS_ENABLED` | `groq` | Providers whose credentials the proxy holds (dev: `groq,bedrock`). |
| `LITELLM_ADMIN_API_KEY` | = `LITELLM_API_KEY` | Key used for `/model/new` / `/model/delete`. |
| `FINOPS_MONTHLY_BUDGET_USD` | `0` | Budget gauge. |

Local stack: `docker compose up -d` (Jaeger, Postgres, LiteLLM) then run the backend natively; `docker compose --profile full up -d` also runs the gateway container. Offline: `tests/mock_llm_upstream.py` + `docker-compose.mock.yml`.

## 10. Rollout and rollback

1. **Local** (done): compose stack, backend in `proxy` mode with `GROQ_API_KEY` blank; unit tests, scenario suite, dashboards populated.
2. **Dev AWS** (done 2026-10-02 as a fresh stack in account 767141477889, see [aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md](aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md)): secrets applied and populated, `ecs-litellm-proxy` and `ecs-ai-gateway` deployed from reviewed plans, `/gateway/health` reports `application_holds_provider_key: false`. The gateway temporarily uses the master key (TD-25) until a scoped virtual key is issued from inside the VPC.
3. **Rollback**: set `llm_gateway_mode = "direct"` in the gateway Terragrunt inputs (re-mounts `GROQ_API_KEY`) and redeploy the gateway task; the proxy can stay running.

## 11. Risks and open questions

| Risk | Mitigation |
|---|---|
| LiteLLM header names change between versions. | Client reads every header defensively; falls back to `estimated` cost and logs cost source; pin the image tag in prod. |
| Shared Aurora database for LiteLLM tables in dev. | Separate database/schema and credentials in prod (Sprint 2). |
| Dual Langfuse emission when configured on both tiers. | Document proxy-only configuration; remove app decorators in Sprint 3. |
| Judge model change alters evaluation scores. | Default unchanged; the Evaluation dashboard already splits by engine; add judge-model dimension in Sprint 3. |
| Groq account serves only `openai/gpt-oss-*` models (no llama-3.x). | `litellm/config.yaml` lists only served models; `/gateway/health` flags `default_model_available: false` if the default disappears. |

## 12. Verification evidence (2026-10-02, local, mock upstream)

- Unit tests: `backend/tests/test_llm_client.py` — 10 passed (header parsing, cost fallback, error normalisation, no-bypass, sync path, allowlist, FinOps/AIOps aggregation).
- Proxy: `x-litellm-response-cost`, `-call-id`, `-attempted-retries`, `-attempted-fallbacks`, `-overhead-duration-ms` returned; 56–94 ms proxy overhead.
- Gateway: code-mode chat `cost_source=litellm`; framework-mode chat with TruLens judge via proxy (`evaluator_engine=trulens`), Ragas heuristic fallback (mock cannot satisfy Ragas' schema — expected `DEGRADED`); `mock-fail` produced a LiteLLM fallback (`fallbacks: 1`, served `mock-judge`); `mock-slow` recorded 2017 ms; blocked prompt made no model call.
- Reports: FinOps 19 calls / $0.000523, judge share 52 %, budget `ok`; AIOps availability 1.0, p50 6 ms, p95 4143 ms, fallbacks 1, all dependencies `ok`.
- Tracing: Jaeger lists `responsible-ai-chat-agent` and `litellm-proxy`.
- Infrastructure: `terraform validate` passes for `ecs-litellm-proxy`, `ecs-ai-gateway`, `secrets`, `aurora-postgres`.
- Real Groq path: proxy retried twice, fell back, and surfaced Groq's `invalid_api_key` as a clean 401 — the routing works; the key was then rotated.

### AWS dev (2026-10-02, account 767141477889, image `aed1bb5`)

- Authenticated smoke test through API Gateway (temporary Cognito admin, deleted afterwards): `/gateway/health` → `mode: proxy`, reachable, 4 models, default available, `application_holds_provider_key: false`; code-mode chat 597 ms, `cost_source: litellm`; framework-mode chat with Presidio, Guardrails, Ragas (1.0) and TruLens (0.1) real engines; `/reports/finops` and `/reports/aiops` populated; Aurora `postgresql`; X-Ray tracing enabled; CORS preflight from CloudFront → 200.
- Defect found during verification and fixed in `aed1bb5`: `Guard.validate('')` fails on empty text, so a GPT-OSS answer whose token budget was consumed by reasoning was reported as a safety block. Empty text is now skipped and an explicit "no text produced" answer with `finish_reason` is returned; re-verified in AWS (`finish_reason=length`, not blocked).
