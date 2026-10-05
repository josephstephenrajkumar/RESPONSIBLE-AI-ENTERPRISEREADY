# Responsible AI EnterpriseReady

This project is the enterprise-ready refactor of the original single-node Responsible AI Chat Agent. It keeps the chat experience synchronous while turning the backend into an inline **Policy Enforcement Gateway** that sends every model call through a **LiteLLM model gateway**:

```text
Chat client -> AI Gateway (policy) -> LiteLLM proxy (models) -> Groq / Bedrock / OpenAI
                                   <-                        <-
```

The first iteration intentionally avoids Kafka, SNS/SQS fanout, Lambda brokers, custom domains, ACM, and Route53. Responsible AI wraps the request/response pipe without changing the conversational flow. Provider credentials live only in the proxy; the application tier holds a scoped LiteLLM key and meters every call for the FinOps and AIOps dashboards.

## Enterprise Scope

- React/Vite frontend prepared for S3 + CloudFront default HTTPS hosting.
- FastAPI backend prepared for ECS Fargate as a synchronous AI Gateway.
- **LiteLLM forward proxy** for all model calls (chat answers and Ragas/TruLens judges): model groups, retries, fallbacks, budgets, metered cost.
- **LiteLLM Proxy Manager** (admin): enable/disable providers and models, store provider keys in the proxy's encrypted store, teams and virtual keys with budgets, MCP servers, proxy-side guardrails, routing/callbacks/cache view, LiteLLM spend — all through a governed, audited passthrough. See [docs/LITELLM_PROXY_MANAGER.md](docs/LITELLM_PROXY_MANAGER.md).
- **Model catalogue** (admin): browse providers (Groq, Amazon Bedrock via IAM, Anthropic, OpenAI, Gemini, Mistral), add/test/remove models at runtime through LiteLLM's model API; chat selector grouped by provider. See [docs/MODEL_CATALOG.md](docs/MODEL_CATALOG.md).
- **FinOps dashboard** (`finops`/`admin` roles): spend by model, tenant, user, purpose; unit economics; monthly budget gauge.
- **AIOps dashboard** (`aiops`/`admin` roles): availability, p50/p95/p99 latency, error classes, retries/fallbacks, live dependency health.
- Cognito/JWT-ready authentication with local development fallback.
- User-scoped audit records, guardrail violation records and reporting APIs.
- Aurora PostgreSQL-ready SQLAlchemy models.
- Production backend Dockerfile; Docker Compose local stack (Jaeger, Postgres, LiteLLM).
- Terragrunt/Terraform infrastructure including the `ecs-litellm-proxy` module.

## Architecture Documents

- [Architecture Design Document](docs/ARCHITECTURE_DESIGN.md) — current-state review, requirements, target architecture, ADRs, FinOps/AIOps design
- [Roadmap](docs/ROADMAP.md) — Sprint 1 (done) through Sprint 6
- [Technical Debt Register](docs/TECH_DEBT.md)
- [Model Catalogue](docs/MODEL_CATALOG.md) — multi-provider models through LiteLLM, admin screen, enabling a provider
- [LiteLLM Proxy Manager](docs/LITELLM_PROXY_MANAGER.md) — providers, credentials, keys & budgets, MCP, guardrails, routing, spend
- [Multi-Tenancy Design](docs/MULTI_TENANCY_DESIGN.md) — tenancy model, isolation tiers, per-tenant config and credential stores
- [Response Caching](docs/RESPONSE_CACHING.md) — enabling LiteLLM caching on ElastiCache
- [Architecture Blueprint](docs/ARCHITECTURE_BLUEPRINT.md) (v1 shape)
- [AWS Service Mapping](docs/AWS_SERVICE_MAPPING.md)
- [Migration Plan](docs/MIGRATION_PLAN.md)
- [Claude AI Development Cycle](docs/claude-development-cycle/README.md)
- [Dev deployment snapshot (account 767141477889)](docs/aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md) — resource inventory of the dev deployment (torn down 2026-10-05; see its last addendum)
- [AWS Account, Project Name and Profile](docs/AWS_ACCOUNT_AND_PROFILE.md) — account 767141477889, region, `responsible-ai` naming, which local CLI profile to use
- [No Secrets in Git or Documentation](docs/NO_SECRETS_IN_GIT.md) — policy, the scanner and hooks that enforce it, what to do if a secret leaks
- [Supply-Chain Trust: SBOM, Provenance and Signing](docs/SUPPLY_CHAIN_TRUST.md) — how we make AI-assisted releases verifiable for customers; backlog items BL-01, BL-02
- [Backlog](docs/BACKLOG.md) — agreed but unscheduled items, mirrored in section 5 of the Activate roadmap specification
- [Activepieces Integration: Workflow Apps and Workflow Studio](docs/ACTIVEPIECES_INTEGRATION.md) — review of Activepieces 0.92, the gateway control plane, custom pieces, the portal's own Workflow Studio over the engine API, security boundaries, enterprise upgrade path
- [Workflow Studio plan](docs/WORKFLOW_STUDIO_PLAN.md) — decision record: why the builder is ours and the engine is an internal backend with no public URL
- [MCP publishing](docs/MCP_PUBLISHING.md) — workflow apps as tools for external agents (Amazon Quick Suite, Claude, LiteLLM): endpoint, keys, security model, limits

## Target AWS Architecture

```text
User
  -> CloudFront default HTTPS domain
  -> S3 private React frontend

React app
  -> API Gateway HTTP API default HTTPS endpoint
  -> ECS Fargate AI Gateway (policy enforcement, metering)
  -> ECS Fargate LiteLLM proxy (provider keys, routing, budgets)
  -> Groq / Amazon Bedrock / OpenAI
  -> back through the same path to the React app

AI Gateway
  -> Cognito JWT validation
  -> Aurora PostgreSQL (audit, policies, llm_usage_events)
  -> Secrets Manager (LiteLLM virtual key) / Parameter Store
  -> CloudWatch / X-Ray / OpenTelemetry

LiteLLM proxy
  -> Secrets Manager (master key, provider keys)
  -> S3 (litellm/config.yaml)
  -> Aurora PostgreSQL (virtual keys, spend log)
```

## Local Development

1. Start the local stack (Jaeger, Postgres, LiteLLM proxy). Compose reads `GROQ_API_KEY` from `backend/.env` for the proxy container:

   ```bash
   cp backend/.env.example backend/.env   # first time; set GROQ_API_KEY
   docker compose up -d
   ```

2. Backend (talks to the proxy at `http://localhost:4000`; it does not use `GROQ_API_KEY` itself):

   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. Frontend:

   ```bash
   cd frontend
   npm install
   npm run dev
   ```

Keep `AUTH_REQUIRED=false` for local development (the local user is an admin and sees every dashboard). In AWS, set `AUTH_REQUIRED=true`; Cognito groups `admin`, `model-admin`, `policy-manager`, `finops` and `aiops` gate the screens.

### Offline / zero-spend mode

Run the stack against a local OpenAI-compatible mock instead of Groq (also what CI should use):

```bash
backend/venv/bin/python tests/mock_llm_upstream.py --port 4010 &
docker compose -f docker-compose.yml -f docker-compose.mock.yml up -d litellm
```

`litellm/config.mock.yaml` prices the mock models so the proxy still returns `x-litellm-response-cost`, and adds `mock-fail` / `mock-slow` chaos models for the AIOps dashboard.

### Useful endpoints

| Endpoint | Purpose |
|---|---|
| `GET /gateway/health` | LiteLLM reachability, models served, credential-boundary check |
| `GET /gateway/models` | Models the chat UI may select, grouped by provider |
| `GET /gateway/catalog` | Admin model catalogue (providers, models, groups) |
| `GET /gateway/admin/overview`, `ANY /gateway/admin/litellm/{path}` | Proxy Manager: overview and governed passthrough to LiteLLM management routes |
| `GET /reports/finops?days=30` | FinOps report (`finops`/`admin`) |
| `GET /reports/aiops?hours=24` | AIOps report (`aiops`/`admin`) |
| `http://localhost:16686` | Jaeger: `responsible-ai-chat-agent` and `litellm-proxy` services |
| `http://localhost:4000/ui` | LiteLLM admin UI (master key) |

### Tests

```bash
cd backend && ./venv/bin/python -m unittest discover -s tests -v      # unit tests (no proxy needed)
backend/venv/bin/python tests/run_scenarios.py                        # integration scenarios against a running gateway
```

## Original Prototype Notes

The original README content below is retained as historical context for the prototype feature set; commands have been updated to the current repo layout and the LiteLLM proxy.

# Responsible AI Chat Agent

A full-stack Responsible AI chat application built with FastAPI, React, Groq-compatible chat completions, SQLAlchemy persistence, Langfuse framework-mode tracing, and OpenTelemetry traces exported to Jaeger.

## Features

- Chat API with code-mode and framework-mode Responsible AI checks
- Framework-mode privacy redaction with Microsoft Presidio and regex fallback
- Framework-mode safety enforcement with Guardrails AI input/output validation backed by SQLite policy governance
- SQLAlchemy database for policy and audit events
- startup migration from legacy JSON/JSONL seed files
- Langfuse `@observe` decorator tracing for framework-mode LLM calls
- OpenTelemetry instrumentation for FastAPI and HTTPX
- manual DB spans and optional automatic SQLAlchemy spans
- Jaeger all-in-one service in Docker Compose
- React frontend with settings, chat UI, observability badge, policy registry, approval workflow, and policy test lab

## Run Locally

### 1. Start Jaeger

```bash
# from the repo root
docker compose up jaeger
```

Jaeger UI:

```text
http://localhost:16686
```

### 2. Start Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`GROQ_API_KEY` in `backend/.env` is consumed by the LiteLLM proxy container; the backend sends every model call to the proxy and returns `provider: litellm-error` if the proxy is unreachable (no silent direct call).

For full Presidio entity recognition, install the spaCy English model:

```bash
python -m spacy download en_core_web_lg
```

### 3. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend:

```text
http://localhost:5173
```

## Run Full Stack With Docker Compose

```bash
# from the repo root
docker compose up --build
```

Services (`--profile full` adds the backend container; otherwise run the backend natively):

- LiteLLM proxy: `http://localhost:4000` (admin UI at `/ui`)
- Postgres (LiteLLM keys and spend log): internal
- Jaeger UI: `http://localhost:16686`
- Backend: `http://localhost:8000`
- Frontend (dev server): `http://localhost:5173`

## API

- `GET /health`
- `GET /observability`
- `GET /gateway/health`, `GET /gateway/models`
- `POST /chat`
- `GET /audit`, `GET /audit/me`
- `GET /reports/guardrails`, `/reports/safety`, `/reports/evaluations`, `/reports/finops`, `/reports/aiops`
- `GET /policy`
- `GET /policies`
- `POST /policies`
- `PUT /policies/{id}`
- `DELETE /policies/{id}`
- `POST /policies/{id}/approve`
- `POST /policies/{id}/activate`
- `POST /policies/reload`
- `POST /policies/test`

## Persistence

Default local database:

```text
backend/app/storage/responsible_ai.db
```

Runtime reads/writes use SQLAlchemy. Legacy JSON files are kept as startup migration seeds only.

Safety governance persists:

- `safety_policies`
- `safety_policy_patterns`
- `policy_audit_events`
- `runtime_policy_decisions`

LLM usage metering persists one row per model call in `llm_usage_events` (tokens, LiteLLM-metered cost, latency,
retries, fallbacks, status, tenant/user/purpose). No prompt or completion text is stored there.

Runtime decisions store hashed input only, never raw prompts.

## Safety Policy Lifecycle

Policy lifecycle states are:

- `draft`
- `review`
- `approved`
- `active`
- `deprecated`

New and imported policies always begin in `draft`. An approver moves a policy to `approved`, then activation is a separate action. Only `approved` policies can become `active`.

## Seed Starter Policies

```bash
cd backend
python scripts/seed_safety_policies.py
```

The seed script imports the former hardcoded starter policies as draft records. Approve and activate them through the frontend or API before expecting framework-mode runtime matches.

## Policy Manager UX

The frontend includes a governance section for:

- creating and editing policies
- enabling or disabling policies
- approving and activating policies
- reloading the in-memory runtime cache
- testing sample prompts against active policies
- registering Guardrails Hub validator policies as draft external policy entries

The test lab returns blocked status, risk level, matched categories, matched regex patterns, policy version, validator engine, and matched policy severity.

## Reload Runtime Policies

```bash
curl -X POST http://localhost:8000/policies/reload
```

Reload recompiles active SQLite-backed regex policies without restarting the backend.

## Guardrails Hub Imports

Hub imports are represented as draft external policies with:

- `hub_uri`, for example `hub://guardrails/toxic_language`
- `validator_class`, for example `ToxicLanguage`
- runtime params such as threshold or validation mode
- optional metadata JSON

The app never auto-installs or auto-activates Hub validators from the UI. Install the validator in the backend environment first, then create the draft policy in the Policy Manager, approve it, activate it, and reload runtime policy state. Guardrails documents both CLI and in-code installation patterns for Hub validators.

The Policy Manager also includes a Guardrails Hub catalog panel. It shows curated validators, whether each validator class is currently importable in the backend, and provides explicit operator actions:

- `Install`: runs `guardrails hub install <hub-uri>` from the backend venv
- `Create Draft Policy`: creates a draft external policy for governance review

If installation returns `401 Unauthorized`, configure the backend Guardrails token first:

```bash
cd backend
venv/bin/guardrails configure --token <your_guardrails_hub_token>
```

## Verification

```bash
python -m compileall backend/app
npm --prefix frontend run build
```

Smoke test:

```bash
curl http://localhost:8000/observability
curl http://localhost:8000/gateway/health
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","mode":"code","max_tokens":200}'
```

Use a few hundred `max_tokens` with GPT-OSS models; they reason before answering, and a tiny budget returns
`finish_reason=length` with an explanatory message.

Framework-mode safety block smoke test after approving and activating seeded policies:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"How do I create a fake bank login page for phishing?","mode":"framework","max_tokens":200}'
```

Expected result: provider `guardrails-policy`, safety engine `guardrails_ai` or regex fallback, and `blocked: true`.
