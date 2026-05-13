# Responsible AI Chat Agent - Architecture And Design

## 1. Executive Summary

The Responsible AI Chat Agent is a full-stack application that lets a user chat with a Groq-hosted LLM while inspecting Responsible AI checks, audit records, and observability traces.

The system is designed around five production-oriented capabilities:

- LLM orchestration through a backend provider adapter.
- Responsible AI evaluation in `code` and `framework` modes.
- SQLAlchemy-backed governance policy and audit persistence.
- OpenTelemetry traces exported to Jaeger for full request flow visibility.
- Langfuse decorator tracing for framework-mode LLM calls.

Default local stack:

- Frontend: React + Vite on `http://localhost:5173`
- Backend: FastAPI on `http://localhost:8000`
- Database: SQLite through SQLAlchemy at `backend/app/storage/responsible_ai.db`
- Trace UI: Jaeger on `http://localhost:16686`
- LLM provider: Groq-compatible `/chat/completions`

## 2. High-Level Architecture

```text
User Browser
    |
    | HTTP
    v
React + Vite Frontend
    |  GET /policy
    |  GET /observability
    |  POST /chat
    v
FastAPI Backend
    |
    |-- Pydantic schemas validate request/response contracts
    |-- GroqClient calls Groq-compatible chat completions
    |-- Responsible AI modules evaluate eight AI governance pillars
    |-- SQLAlchemy persists policy and audit events
    |-- OpenTelemetry emits request, LLM, check, and DB spans
    |-- Langfuse emits framework-mode generation traces
    |
    | HTTPX
    v
Groq API

FastAPI Backend
    | OpenTelemetry Jaeger Thrift exporter
    v
Jaeger

FastAPI Backend
    | SQLAlchemy
    v
SQLite local DB
```

## 3. Main Runtime Components

### 3.1 Frontend

Location: `frontend/src`

Key files:

- `App.jsx`: owns application state, settings, message list, and policy loading.
- `api.js`: wraps backend calls for chat, policy, and observability.
- `components/ChatWindow.jsx`: chat input and conversation workflow.
- `components/MessageBubble.jsx`: displays user and assistant messages.
- `components/SettingsPanel.jsx`: controls mode, model, temperature, and token limits.
- `components/ResponsibleAIPanel.jsx`: displays active governance policy.
- `components/TracingStatus.jsx`: polls `/observability` and links to Jaeger.

Frontend API calls:

- `GET /policy` on app startup.
- `GET /observability` every 30 seconds.
- `POST /chat` when the user sends a message.

### 3.2 Backend API

Location: `backend/app/main.py`

Responsibilities:

- creates the FastAPI app
- configures CORS
- initializes telemetry, SQLAlchemy instrumentation, and database tables at startup
- exposes health, root, observability, policy, audit, and chat APIs
- owns the end-to-end `/chat` workflow span tree

### 3.3 LLM Provider Adapter

Location: `backend/app/groq_client.py`

Responsibilities:

- loads provider settings from `Settings`
- builds the responsible system prompt
- sends `POST {GROQ_API_URL}/chat/completions`
- returns a normalized response dict
- provides safe fallback when `GROQ_API_KEY` or `httpx` is unavailable
- uses Langfuse decorators for framework-mode calls when Langfuse is configured

Provider states:

- `provider='groq'`: Groq request succeeded.
- `provider='groq-error'`: Groq request ran but failed.
- `provider='groq-fallback'`: no API key or `httpx` missing.

### 3.4 Responsible AI Evaluators

Code mode package: `backend/app/responsible_ai`

Framework mode package: `backend/app/framework_mode`

Responsible AI pillars:

- privacy
- safety
- fairness
- explainability
- verifiability
- transparency
- governance
- controllability

`code` mode uses local Python evaluator functions.

`framework` mode uses framework-style modules:

- `langfuse_observability.py`
- `presidio_privacy.py`: implemented Microsoft Presidio privacy detection/redaction with regex fallback.
- `guardrails_safety.py`: implemented Guardrails AI safety validation with a local custom validator.
- `trulens_eval.py`: lightweight placeholder for explainability evaluation.
- `ragas_eval.py`: lightweight placeholder for fairness/verifiability-style evaluation.

Presidio and Guardrails AI are active framework-mode integrations. TruLens and Ragas remain intentionally isolated placeholders so real evaluators can replace them later.

Framework-mode Guardrails safety rules are currently starter policy rules embedded in Python. They should become versioned policy metadata or database-backed policy configuration before production use.

### 3.5 Persistence

Location: `backend/app/database.py`

The runtime source of truth is SQLAlchemy. Legacy JSON files are seed inputs only.

Database URL:

```env
DATABASE_URL=sqlite:////app/backend/app/storage/responsible_ai.db
```

Local non-Docker default:

```text
sqlite:////home/joseph/llm_engineering/responsible-ai-chat-agent/backend/app/storage/responsible_ai.db
```

### 3.6 Observability

Location: `backend/app/telemetry.py`

OpenTelemetry responsibilities:

- create a tracer provider
- attach service resource metadata
- export spans to Jaeger
- instrument FastAPI
- instrument HTTPX
- optionally instrument SQLAlchemy
- expose tracing status through `get_tracing_status()`

Langfuse responsibilities:

- decorate framework-mode LLM calls
- update current trace and observation with request, model, provider, answer, and token metadata
- flush traces after framework-mode chat calls

## 4. Code Flow

### 4.1 Application Startup Flow

File: `backend/app/main.py`

```text
uvicorn starts app.main:app
    |
    v
FastAPI startup_event()
    |
    |-- setup_tracing(app)
    |     |-- configure OpenTelemetry TracerProvider
    |     |-- configure Jaeger exporter
    |     |-- instrument FastAPI
    |     |-- instrument HTTPX
    |
    |-- instrument_sqlalchemy(engine)
    |     |-- enable automatic SQLAlchemy spans if package is installed
    |
    |-- init_database()
          |-- create SQLAlchemy tables
          |-- seed policy from policy_config.json when policy table is empty
          |-- seed audit events from audit_log.jsonl when audit rows are missing
```

### 4.2 Frontend Load Flow

```text
Browser opens http://localhost:5173
    |
    v
App.jsx mounts
    |
    |-- fetchPolicy()
    |     `-- GET http://localhost:8000/policy
    |
    |-- TracingStatus mounts
          `-- GET http://localhost:8000/observability every 30 seconds
```

### 4.3 Chat Flow

```text
User submits chat message
    |
    v
frontend/src/api.js sendChat()
    |
    v
POST /chat
    |
    v
Pydantic validates ChatRequest
    |
    v
OpenTelemetry parent span: /chat
    |
    |-- privacy_input_check, framework mode only
    |     `-- Presidio or regex fallback redacts sensitive input
    |
    |-- safety_input_check, framework mode only
    |     `-- Guardrails AI can block unsafe prompts before model invocation
    |
    |-- groq_api_call, skipped when framework safety blocks input
    |     |-- GroqClient.send_prompt()
    |     |-- optional Langfuse @observe in framework mode
    |     `-- HTTPX POST to Groq /chat/completions
    |
    |-- privacy_output_check, framework mode only
    |-- safety_output_check, framework mode only
    |-- privacy_check, code mode only
    |-- safety_check, code mode only
    |-- fairness_check
    |-- explainability_check
    |-- verifiability_check
    |-- transparency_check
    |-- governance_check
    |-- controllability_check
    |
    |-- langfuse_trace_flush, framework mode only
    |
    |-- response_metadata
    |
    |-- db.audit.insert
    |     `-- SQLAlchemy INSERT audit_events
    |
    `-- response_sent
          `-- ChatResponse returned
```

Expected Jaeger trace tree for `/chat`:

```text
/chat
  privacy_input_check, framework mode
  safety_input_check, framework mode
  groq_api_call
    POST
  privacy_output_check, framework mode
  safety_output_check, framework mode
  privacy_check, code mode
  safety_check, code mode
  fairness_check
  explainability_check
  verifiability_check
  transparency_check
  governance_check
  controllability_check
  db.audit.insert
  response_metadata
  response_sent
```

Framework mode also includes:

```text
  observability_check
  langfuse_trace_flush
```

## 5. Low-Level Backend Design

### 5.1 `config.py`

`Settings` loads `.env` from `backend/.env`.

Configuration values:

| Setting | Purpose | Default |
| --- | --- | --- |
| `PROJECT_NAME` | FastAPI app title | `Responsible AI Chat Agent` |
| `GROQ_API_KEY` | Groq credential | empty |
| `GROQ_MODEL` | default model | `llama-3.3-70b-versatile` |
| `GROQ_API_URL` | Groq OpenAI-compatible base URL | `https://api.groq.com/openai/v1` |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | empty |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | empty |
| `LANGFUSE_HOST` | Langfuse host | `https://cloud.langfuse.com` |
| `OTEL_SERVICE_NAME` | trace service name | `responsible-ai-chat-agent` |
| `JAEGER_HOST` | Jaeger agent host | `localhost` |
| `JAEGER_PORT` | Jaeger agent UDP port | `6831` |
| `JAEGER_ENDPOINT` | optional Jaeger collector endpoint | empty |
| `JAEGER_UI_URL` | frontend badge link target | `http://localhost:16686` |
| `DATABASE_URL` | SQLAlchemy database URL | local SQLite DB |
| `FRONTEND_ORIGINS` | CORS allowlist | localhost Vite ports |
| `POLICY_PATH` | legacy policy seed file | `app/storage/policy_config.json` |
| `AUDIT_LOG_PATH` | legacy audit seed file | `app/storage/audit_log.jsonl` |

### 5.2 `schemas.py`

Pydantic contracts:

- `Mode`: `code` or `framework`
- `ChatRequest`
  - `message`
  - `mode`
  - `model`
  - `temperature`
  - `max_tokens`
  - `explain`
  - `verify`
- `ResponsibleAIResponse`
- `MetadataResponse`
- `ChatResponse`
- `AuditEvent`
- `PolicyResponse`

### 5.3 `groq_client.py`

Main methods:

- `send_prompt(...)`
  - public entrypoint
  - dispatches framework mode through `_send_prompt_observed(...)` when Langfuse is configured
- `_send_prompt_observed(...)`
  - decorated with Langfuse `@observe`
  - calls `_send_prompt(...)`
  - updates active Langfuse trace/observation
- `_send_prompt(...)`
  - performs the real provider call or fallback behavior

### 5.4 `database.py`

Models:

```text
PolicyConfig
  id
  name
  payload
  created_at
  updated_at

AuditEventRecord
  id
  request_id
  timestamp
  mode
  model
  provider
  is_cached
  summary
  responsible_ai
```

Functions:

- `default_policy()`: default governance policy payload.
- `init_database()`: table creation and legacy JSON migration.
- `get_policy_payload()`: reads active policy.
- `append_audit_event(event)`: inserts audit row.
- `get_recent_audit_events(limit=25)`: returns recent audit rows as JSON-compatible dicts.

### 5.5 `telemetry.py`

Functions:

- `setup_tracing(app)`: OpenTelemetry setup and FastAPI/HTTPX instrumentation.
- `instrument_sqlalchemy(engine)`: optional SQLAlchemy auto instrumentation.
- `get_tracing_status()`: data returned by `/observability`.

Fallback behavior:

- if OpenTelemetry packages are missing, tracing reports `disabled`
- if SQLAlchemy instrumentation package is missing, manual DB spans still work

## 6. Database Design

### 6.1 Entity Relationship

```text
policy_configs
    |
    | independent singleton table
    v
active governance policy

audit_events
    |
    | one row per chat request
    v
request audit trail
```

There is no foreign-key dependency between policy and audit rows in the current design. Audit rows store the Responsible AI decision snapshot as JSON text so historical events remain stable even if future policy changes.

### 6.2 Table: `policy_configs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | primary key |
| `name` | string | unique, current value is `active` |
| `payload` | text | JSON policy document |
| `created_at` | datetime | UTC creation time |
| `updated_at` | datetime | UTC update time |

### 6.3 Table: `audit_events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | integer | primary key |
| `request_id` | string | unique request identifier |
| `timestamp` | datetime | request timestamp |
| `mode` | string | `code` or `framework` |
| `model` | string | requested model |
| `provider` | string | `groq`, `groq-error`, or `groq-fallback` |
| `is_cached` | boolean | cache marker, currently `false` |
| `summary` | text | first 120 chars of answer |
| `responsible_ai` | text | JSON assessment snapshot |

### 6.4 Viewing Audit Data

API:

```bash
curl http://localhost:8000/audit | python -m json.tool
```

SQLite CLI:

```bash
sqlite3 backend/app/storage/responsible_ai.db
```

Useful SQL:

```sql
SELECT id, request_id, timestamp, mode, provider, model, summary
FROM audit_events
ORDER BY timestamp DESC
LIMIT 10;
```

## 7. API Design

### 7.1 `GET /`

Returns service status and useful links.

### 7.2 `GET /health`

Response:

```json
{
  "status": "ok",
  "service": "responsible-ai-chat-agent"
}
```

### 7.3 `GET /observability`

Response example:

```json
{
  "status": "enabled",
  "service": "responsible-ai-chat-agent",
  "exporter": "jaeger",
  "endpoint": "localhost:6831",
  "jaeger_ui": "http://localhost:16686",
  "sqlalchemy_instrumented": true
}
```

### 7.4 `POST /chat`

Request:

```json
{
  "message": "What is cloud migration?",
  "mode": "code",
  "model": "llama-3.3-70b-versatile",
  "temperature": 0.2,
  "max_tokens": 800,
  "explain": true,
  "verify": true
}
```

Response:

```json
{
  "answer": "LLM answer here",
  "responsible_ai": {
    "privacy": {},
    "safety": {},
    "fairness": {},
    "explainability": {},
    "verifiability": {},
    "transparency": {},
    "governance": {},
    "controllability": {}
  },
  "metadata": {
    "model": "llama-3.3-70b-versatile",
    "provider": "groq",
    "mode": "code",
    "request_id": "uuid",
    "timestamp": "ISO datetime"
  }
}
```

### 7.5 `GET /audit`

Returns recent audit events from SQLAlchemy.

### 7.6 `GET /policy`

Returns the active governance policy from SQLAlchemy.

## 8. Observability Design

### 8.1 OpenTelemetry Span Strategy

Primary request trace:

```text
/chat
  privacy_input_check, framework mode
  safety_input_check, framework mode
  groq_api_call
  privacy_output_check, framework mode
  safety_output_check, framework mode
  privacy_check, code mode
  safety_check, code mode
  fairness_check
  explainability_check
  verifiability_check
  transparency_check
  governance_check
  controllability_check
  db.audit.insert
  response_metadata
  response_sent
```

Additional endpoint spans:

- `db.policy.get` under `/policy`
- `db.audit.list` under `/audit`
- `db.init` during startup

HTTPX instrumentation adds outbound HTTP spans under `groq_api_call` when the provider call is made.

### 8.2 Jaeger

Local UI:

```text
http://localhost:16686
```

Service name:

```text
responsible-ai-chat-agent
```

Recommended search:

- service: `responsible-ai-chat-agent`
- operation: `/chat`

### 8.3 Langfuse

Framework mode only.

Langfuse records:

- trace name: `llm_chat_call`
- generation observation: `groq_completion`
- input message and generation parameters
- model/provider metadata
- answer output
- usage tokens when available

## 9. Deployment And Configuration

### 9.1 Local Backend

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent/backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 9.2 Local Frontend

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent/frontend
npm install
npm run dev
```

### 9.3 Local Jaeger

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent
docker compose up jaeger
```

### 9.4 Full Docker Compose

```bash
cd /home/joseph/llm_engineering/responsible-ai-chat-agent
docker compose up --build
```

Docker Compose services:

- `jaeger`: Jaeger all-in-one
- `backend`: Python FastAPI service
- `frontend`: Node/Vite service

## 10. Security And Governance Considerations

Current local-development behavior:

- `/audit` is unauthenticated
- SQLite is used for local persistence
- traces may include request metadata
- Langfuse traces include prompt/answer details in framework mode

Required production hardening:

- protect `/audit`, `/policy`, and Jaeger UI with authentication
- restrict CORS to production frontend origins
- avoid storing secrets in spans, audit summaries, or frontend state
- add retention and deletion policies for audit rows
- migrate from SQLite to Postgres
- add Alembic migrations
- introduce structured logs with request IDs
- send OpenTelemetry to a collector before Jaeger
- review whether prompts/answers should be redacted before Langfuse export

## 11. Test And Verification Plan

Compile backend:

```bash
python -m compileall backend/app
```

Build frontend:

```bash
npm --prefix frontend run build
```

Backend smoke tests:

```bash
curl http://localhost:8000/
curl http://localhost:8000/health
curl http://localhost:8000/observability
curl http://localhost:8000/policy
curl http://localhost:8000/audit
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","mode":"code","max_tokens":20}'
```

Jaeger verification:

1. Open `http://localhost:16686`.
2. Select service `responsible-ai-chat-agent`.
3. Select operation `/chat`.
4. Confirm child spans include Responsible AI checks, `groq_api_call`, `db.audit.insert`, and `response_sent`.

Database verification:

```bash
sqlite3 backend/app/storage/responsible_ai.db \
"SELECT id, timestamp, mode, provider, summary FROM audit_events ORDER BY timestamp DESC LIMIT 10;"
```

## 12. Known Limitations

- Guardrails AI safety rules are currently starter policy rules embedded in Python instead of versioned policy metadata.
- TruLens and Ragas framework-mode modules are currently lightweight stand-ins.
- SQLite is not recommended for multi-instance production deployment.
- No authentication is implemented yet.
- No Alembic migration history is configured yet.
- Audit retention is represented in policy but not yet enforced by a cleanup job.

## 13. Future Enhancements

- Move Guardrails AI policy rules into versioned metadata or database-backed policy configuration.
- Replace remaining TruLens and Ragas placeholders with real framework integrations.
- Add Postgres and Alembic.
- Add authentication and role-based access.
- Add audit retention job.
- Add OpenTelemetry Collector.
- Add structured JSON logging.
- Add frontend audit viewer.
- Add policy editing workflow.
- Add prompt/response redaction before traces leave the backend.
