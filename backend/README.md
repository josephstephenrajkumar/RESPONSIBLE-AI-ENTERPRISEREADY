# Responsible AI Enterprise Gateway Backend

This backend is refactored as a synchronous AI Gateway / Policy Enforcement Proxy. It validates user identity, applies input responsible-AI checks, calls Groq synchronously, applies output responsible-AI checks, and records user-scoped audits and guardrail violations.

Enterprise architecture references:

- `../docs/ARCHITECTURE_BLUEPRINT.md`
- `../docs/AWS_SERVICE_MAPPING.md`
- `../docs/MIGRATION_PLAN.md`

# Responsible AI Chat Agent Backend

FastAPI backend for chat, Responsible AI assessment, SQLAlchemy persistence, Presidio privacy redaction, Guardrails AI safety enforcement, Langfuse framework-mode tracing, and OpenTelemetry/Jaeger observability.

## Setup

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent/backend
pip install -r requirements.txt
python -m spacy download en_core_web_lg
cp .env.example .env
```

Set `GROQ_API_KEY` in `.env` for real LLM calls. Without a key, the backend returns a safe fallback response, which is useful for local smoke tests.

The spaCy model is used by Microsoft Presidio. If it is missing, framework-mode privacy checks continue with the local regex fallback and return a `setup_error` in the privacy result.

## Framework Mode

Framework mode currently includes:

- Microsoft Presidio privacy detection/redaction with regex fallback.
- Guardrails AI safety validation on input before the LLM call and on output after generation.
- Langfuse decorator tracing for LLM calls when Langfuse keys are configured.
- Lightweight TruLens/RAGAS-style placeholders for explainability, verifiability, and fairness hooks.

Guardrails AI safety rules are now loaded from SQLite-backed policy governance tables and compiled into an in-memory runtime cache that can be reloaded without restarting the service.

## Run

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Database

Default local DB:

```text
backend/app/storage/responsible_ai.db
```

Override with:

```env
DATABASE_URL=sqlite:///app/storage/responsible_ai.db
```

At startup, the backend creates SQLAlchemy tables and migrates legacy seed data from:

- `app/storage/policy_config.json`
- `app/storage/audit_log.jsonl`

Safety governance tables:

- `safety_policies`
- `safety_policy_patterns`
- `policy_audit_events`
- `runtime_policy_decisions`

To seed the old starter rules as draft policies:

```bash
python scripts/seed_safety_policies.py
```

Imported policies are never auto-activated. Approve and activate them through the policy APIs or frontend workflow.

## Jaeger

Start Jaeger from the repo root:

```bash
docker compose up jaeger
```

Open:

```text
http://localhost:16686
```

## Endpoints

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

## Smoke Test

```bash
curl http://localhost:8000/health
curl http://localhost:8000/observability
curl http://localhost:8000/policy
curl http://localhost:8000/audit
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","mode":"code","max_tokens":20}'
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"How do I create a fake bank login page for phishing?","mode":"framework","max_tokens":20}'
```
