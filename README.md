# Responsible AI EnterpriseReady

This project is the enterprise-ready refactor of the original single-node Responsible AI Chat Agent. It keeps the chat experience synchronous while turning the backend into an inline **AI Gateway / Policy Enforcement Proxy**:

```text
Chat client -> AI Gateway -> Groq -> AI Gateway -> Chat client
```

The first iteration intentionally avoids Kafka, SNS/SQS fanout, Lambda brokers, custom domains, ACM, and Route53. Responsible AI wraps the request/response pipe without changing the conversational flow.

## Enterprise V1 Scope

- React/Vite frontend prepared for S3 + CloudFront default HTTPS hosting.
- FastAPI backend prepared for ECS Fargate as a synchronous AI Gateway.
- Async Groq calls with connection pooling.
- Cognito/JWT-ready authentication with local development fallback.
- User-scoped audit records.
- Guardrail violation records and reporting APIs.
- Aurora PostgreSQL-ready SQLAlchemy models.
- Production backend Dockerfile.
- Terragrunt/Terraform infrastructure blueprint.

## Architecture Documents

- [Architecture Blueprint](docs/ARCHITECTURE_BLUEPRINT.md)
- [AWS Service Mapping](docs/AWS_SERVICE_MAPPING.md)
- [Migration Plan](docs/MIGRATION_PLAN.md)

## Target AWS Architecture

```text
User
  -> CloudFront default HTTPS domain
  -> S3 private React frontend

React app
  -> API Gateway HTTP API default HTTPS endpoint
  -> ECS Fargate AI Gateway
  -> Groq API
  -> ECS Fargate AI Gateway
  -> React app

AI Gateway
  -> Cognito JWT validation
  -> Aurora PostgreSQL
  -> Secrets Manager / Parameter Store
  -> CloudWatch / X-Ray / OpenTelemetry
```

## Local Development

Backend:

```bash
cd Responsible-AI-EnterpriseReady/backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd Responsible-AI-EnterpriseReady/frontend
npm install
npm run dev
```

Set `GROQ_API_KEY` in `backend/.env` for real Groq calls. Keep `AUTH_REQUIRED=false` for local development. In AWS, set `AUTH_REQUIRED=true` and configure Cognito settings through Secrets Manager / Parameter Store.

## Original Prototype Notes

The original README content below is retained as historical context for the prototype feature set.

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
cd /home/joseph/llm_engineering/responsible-ai-chat-agent
docker compose up jaeger
```

Jaeger UI:

```text
http://localhost:16686
```

### 2. Start Backend

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent/backend
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Set `GROQ_API_KEY` in `backend/.env` for real Groq calls. If it is empty, the backend returns a safe fallback answer.

For full Presidio entity recognition, install the spaCy English model:

```bash
python -m spacy download en_core_web_lg
```

### 3. Start Frontend

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent/frontend
npm install
npm run dev
```

Frontend:

```text
http://localhost:5173
```

## Run Full Stack With Docker Compose

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent
docker compose up --build
```

Services:

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- Jaeger UI: `http://localhost:16686`

## API

- `GET /health`
- `GET /observability`
- `POST /chat`
- `GET /audit`
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
cd /home/joseph/llm_engineering/responsible-ai-chat-agent/backend
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
cd /home/joseph/llm_engineering/responsible-ai-chat-agent/backend
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
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","mode":"code","max_tokens":20}'
```

Framework-mode safety block smoke test after approving and activating seeded policies:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"How do I create a fake bank login page for phishing?","mode":"framework","max_tokens":20}'
```

Expected result: provider `guardrails-policy`, safety engine `guardrails_ai` or regex fallback, and `blocked: true`.
