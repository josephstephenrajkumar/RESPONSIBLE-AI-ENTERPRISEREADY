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
- Per-tenant/team virtual keys and budgets (`/team/new`, `/key/generate`), RPM/TPM limits; map Cognito `custom:tenant_id` → LiteLLM team.
- Add Amazon Bedrock models to `model_list` via the task role (no key); keep Groq as fallback.
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

**Exit criteria**: framework-mode p95 drops below the code-mode p95 + 1 s; evaluation coverage and spend reported separately.

### Sprint 4 — Governance, compliance and RBAC

- Tenant-aware policies: policy ownership and activation per tenant; tenant filter on all reports.
- Policy-as-code export/import (YAML) with signed approvals; policy change audit report.
- Audit retention and deletion jobs aligned to `audit_retention_days`; PII-free guarantee tests on audit/metering tables.
- Prompt/response redaction before any trace export (Presidio on the proxy path via LiteLLM guardrail hook or pre-callback).
- Harden admin endpoints: authenticate `/audit`, `/policy`, `/policies/test` (TD-08); move Guardrails Hub installs from the API to the image build (TD-19).
- Compliance exports: monthly CSV/Parquet of audits, violations and spend to S3 for finance and risk.

**Exit criteria**: every report endpoint is tenant-scoped and role-gated; a quarterly compliance export runs unattended.

### Sprint 5 — Scale, resilience and user experience

- ECS autoscaling on request count and p95 for both services; proxy ALB ingress by security group (TD-13).
- LiteLLM caching (Redis/ElastiCache) for repeated prompts; cache-hit rate on the FinOps dashboard.
- Streaming responses end-to-end (SSE) with guardrail output checks on the streamed buffer.
- Circuit breaker and provider health routing (`cooldown_time`, `allowed_fails`) tuned from load tests; multi-region readiness review.
- Frontend: router, per-screen lazy loading, accessible charts, shared chart library consolidation (TD-10, TD-18).

**Exit criteria**: 500 concurrent users sustained in load test with p95 within SLO; cache-hit and fallback rates visible.

### Sprint 6 — Platformisation and chargeback

- Offer the LiteLLM proxy as the organisation's model gateway: self-service team keys, model catalogue, per-team dashboards.
- Showback/chargeback: export spend by tenant/team to AWS Cost and Usage Report via cost allocation tags; FinOps anomaly detection (daily spend deviation).
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
