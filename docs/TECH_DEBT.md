# Technical Debt Register

Found during the 2026-10-02 architecture review. Severity reflects production impact; effort is a planning estimate (S < 1 day, M 1–3 days, L > 3 days). The "Sprint" column links to [ROADMAP.md](ROADMAP.md).

| ID | Area | Debt | Impact | Severity | Effort | Sprint | Status |
|---|---|---|---|---|---|---|---|
| TD-01 | Security | Provider credential (`GROQ_API_KEY`) held by the application tier and used from three code paths. | Credential sprawl; no single egress; outage = chat outage. | High | M | 1 | **Resolved in code** (proxy mode, single client). Dev `.env` and AWS task still carry the key until Sprint 2 apply. |
| TD-02 | DevEx | README/TEST_PLAN reference `docker compose` but no compose file existed. | Onboarding friction; Jaeger started by hand. | Medium | S | 1 | **Resolved** (`docker-compose.yml`, `docker-compose.mock.yml`). |
| TD-03 | Performance / Cost | Ragas and TruLens judges run inline on every framework-mode request (3 model calls per chat). | ~20 s p95; judges ≈ 52 % of spend. | High | L | 3 | Open. Judge model now configurable (`LLM_JUDGE_MODEL`) as a stop-gap. |
| TD-04 | Data | No Alembic; schema evolution via `create_all` and a hand-rolled `_ensure_sqlite_columns`. | Risky Aurora changes; drift between envs. | High | M | 2 | Open. |
| TD-05 | Backend | FastAPI `@app.on_event` startup/shutdown (deprecated). | Future FastAPI upgrade breaks start-up. | Low | S | 2 | Open. |
| TD-06 | Backend | `datetime.utcnow()` naive timestamps throughout. | Deprecated in Python 3.12; timezone bugs in reports. | Low | M | 2 | Open (metering follows existing convention for consistency). |
| TD-07 | Reporting | FinOps/AIOps aggregation in Python over ≤ 20 k rows per request. | Fine for dev; slow and memory-heavy at scale. | Medium | M | 2 | Open. Replace with rollup tables or CloudWatch EMF. |
| TD-08 | Security | `/audit`, `/policy`, `/policies/test` are unauthenticated. | Information disclosure in shared environments. | High | S | 4 | Open. |
| TD-09 | Responsible AI | Framework-mode verifiability, transparency, governance, controllability are static dicts. | Pillars look "implemented" but carry no signal. | Medium | L | 3 | Open. |
| TD-10 | Frontend | Chart primitives duplicated across Evaluation/Guardrails dashboards; new dashboards use `charts.jsx`. | Inconsistent visuals; triple maintenance. | Low | S | 5 | Partially resolved. |
| TD-11 | Observability | Langfuse can be configured on both app and proxy → duplicate generations. | Double counting in Langfuse. | Low | S | 2 | Open. Documented; prefer proxy-only. |
| TD-12 | Infra | Hardcoded account id, secret ARN and CloudFront domain in `infra/live/dev/*.hcl`. | Not portable to stage/prod; secret ARN drift. | Medium | S | 2 | Open. |
| TD-13 | Infra | ALB ingress by `10.0.0.0/8`/VPC CIDR instead of security-group references; `image_tag = latest`; no autoscaling; LiteLLM shares the app Aurora database. | Over-broad network access; non-reproducible deploys; noisy-neighbour risk. | Medium | M | 2 / 5 | Open. |
| TD-14 | Backend | Jaeger UI reverse proxy (`/jaeger/*`) lives in the production app. | Dev-only code path in prod surface. | Low | S | 4 | Open. |
| TD-15 | FinOps | Local fallback price table (`pricing.py`) duplicates LiteLLM's price map. | Estimates drift from list prices. | Low | S | 2 | Accepted: fallback only; `cost_source` makes it visible. |
| TD-16 | Testing | No CI; unit tests only for `llm_client`/aggregations; scenario suite needs a live gateway. | Regressions reach dev. | Medium | M | 2 | Open. Mock mode makes a free CI job possible. |
| TD-17 | Infra | `jwt_secret` secret is provisioned but unused (Cognito signs tokens). | Confusing; unnecessary secret. | Low | S | 2 | Open. |
| TD-18 | Frontend | No router; all state in `App.jsx`; auth token in `localStorage`. | Hard to grow; XSS exposure of token. | Medium | M | 5 | Open. |
| TD-19 | Security / Supply chain | Guardrails Hub validators installed at runtime via `subprocess` from an API call. | Arbitrary package install in prod containers. | High | M | 4 | Open. Move installs to image build. |
| TD-20 | Repo | `backend/vendor/` holds a 12 MB spaCy wheel and the Guardrails tarball. | Repo bloat; slow clones. | Low | S | 2 | Open. Use a private index or build-time download. |
| TD-21 | Dependencies | `langchain-community<0.4` pin for Ragas import chain; unpinned `requirements.txt` otherwise. | Non-reproducible builds. | Medium | S | 2 | Open. Add a lock file. |
| TD-22 | Backend | `code` vs `framework` modes duplicate pillar orchestration in `main.py` (~150 lines). | Hard to extend; easy to desync. | Medium | M | 3 | Open. Extract a pipeline abstraction. |
| TD-23 | FinOps | Budget enforcement is advisory in the gateway (gauge only). | Spend can exceed budget. | Medium | S | 2 | Open. Enforce via LiteLLM key/team budgets. |
| TD-24 | Infra | `ecs-ai-gateway/README.md` and `AWS_SERVICE_MAPPING.md` describe direct Groq calls. | Docs drift. | Low | S | 1 | **Resolved** in this change. |
| TD-25 | Security | Dev gateway task uses the LiteLLM **master key** as `LITELLM_API_KEY` because the proxy ALB is VPC-internal and `/key/generate` cannot be called from outside yet. | Gateway can reach proxy admin routes; no per-service budget scope. | High | S | 2 | Open. Issue a scoped virtual key from inside the VPC (ECS Exec or a one-off task) and store it in `litellm_gateway_key`. |
| TD-26 | Responsible AI | Presidio input redaction removes common tokens (observed: "AI" in "what does an AI gateway do?"), so the model answered about a "PII gateway". | Silent prompt distortion in framework mode. | Medium | S | 3 | Open. Tune recognizers/score threshold and add an allowlist; add a scenario asserting the prompt meaning survives redaction. |
| TD-27 | Proxy Manager | LiteLLM capabilities are hard-coded: static route allow-list, static provider registry, proxy image on the floating `main-stable` tag. | New LiteLLM features need code to appear; an unnoticed image change can alter behaviour. | Medium | M | 3 | Open. Capability manifest from `/routes`/`/openapi.json`, dynamic allow-list, provider registry from `/public/providers/fields`, pinned image tag. |
| TD-28 | Frontend | Cognito ID token (1 h) was never refreshed; after an hour every screen failed with *Invalid authentication token*. | Admin screens unusable after 60 min. | High | S | — | **Resolved** 2026-10-02: refresh-token flow, proactive refresh, 401 retry, session-expired prompt. |
| TD-29 | LiteLLM | `litellm_settings.request_timeout` saved via `/config/update` is persisted but `/settings` keeps reporting the process default (6000 s) until the proxy restarts; router `timeout` governs per-request timeouts in practice. Key regenerate and some settings fields are LiteLLM Enterprise-only (rotation implemented gateway-side). | Confusing live value; feature gaps hidden behind licence. | Low | S | — | UI shows both saved and live values; revisit on LiteLLM upgrade. |
| TD-30 | Workflow Apps | The Activepieces chat page (`/chats/{flowId}`) and its sync webhook are public to anyone who knows the flow id (upstream design); the embedded chat relies on that. | Anyone with the id can use a published chat app and spend its budget. | High | M | — | Open. Before internet exposure put the chat behind the gateway proxy (`POST /workflows/apps/{id}/chat`, Cognito) or an authenticating reverse proxy and keep `AP_FRONTEND_URL` internal ([ACTIVEPIECES_INTEGRATION.md](ACTIVEPIECES_INTEGRATION.md) §6). |
| TD-31 | Workflow Apps | Community edition: builders log in to Activepieces as the shared workflow service account (platform admin); no SSO, no per-tenant projects, no piece governance. | Shared credential for builders; every flow visible to every builder. | Medium | L | — | Open. Enterprise licence (managed authentication, project roles, piece sets) or one engine per tenant; the client interface isolates the change (§8). |
| TD-32 | Workflow Apps | Activepieces runs with PGlite and an in-memory queue in compose; no Terraform module, Aurora database, Redis or Secrets Manager wiring for AWS yet. | Not deployable to dev AWS until the module exists. | Medium | M | — | Open. Designed in §5.5; build on the deploy instruction. |

## Principles for paying it down

1. Debt that weakens the **credential boundary** (TD-01, TD-08, TD-19) is scheduled before features.
2. Debt that blocks **measurement** (TD-04, TD-07, TD-16) comes next, because every later sprint depends on trustworthy numbers.
3. Everything else is paid down inside the sprint whose feature touches the same code, and recorded here when it is.
