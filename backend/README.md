# Responsible AI Enterprise Gateway Backend

FastAPI service that acts as the **Policy Enforcement Gateway**: it validates user identity (Cognito JWT),
applies input responsible-AI checks (Presidio privacy, Guardrails safety), sends the model call through the
**LiteLLM proxy**, applies output checks and LLM-judged evaluations (Ragas fairness, TruLens explainability),
and records user-scoped audits, guardrail violations and per-call usage metering for the FinOps and AIOps dashboards.

```text
client -> FastAPI gateway -> LiteLLM proxy -> Groq / Bedrock / OpenAI
             |-- app.llm_client is the only code path that calls a model
             |-- llm_usage_events: tokens, cost, latency, retries, fallbacks per call
             `-- audit_events, guardrail_violations, safety policies
```

Architecture references: [`../docs/ARCHITECTURE_DESIGN.md`](../docs/ARCHITECTURE_DESIGN.md),
[`../docs/RESPONSIBLE_AI_DESIGN.md`](../docs/RESPONSIBLE_AI_DESIGN.md), [`../docs/ROADMAP.md`](../docs/ROADMAP.md).

## Setup

```bash
# from the repo root: start Jaeger, Postgres and the LiteLLM proxy
docker compose up -d

cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install vendor/en_core_web_sm-3.8.0-py3-none-any.whl   # spaCy model for Presidio
cp .env.example .env                                         # set GROQ_API_KEY (used by the proxy container)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`GROQ_API_KEY` in `.env` is read by the LiteLLM container through `docker compose`; the backend itself does not use
it in `proxy` mode. Without a reachable proxy, `/chat` returns `provider: litellm-error` rather than silently calling
a provider. For a zero-spend setup use the mock upstream (see the root README, "Offline / zero-spend mode").

Key settings (`app/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `LLM_GATEWAY_MODE` | `proxy` | `direct` is a break-glass mode that calls Groq with `GROQ_API_KEY` |
| `LITELLM_PROXY_URL` | `http://localhost:4000` | LiteLLM base URL |
| `LITELLM_API_KEY` | — | LiteLLM virtual key (master key locally) |
| `LLM_DEFAULT_MODEL` | `openai/gpt-oss-120b` | must exist in `litellm/config.yaml` |
| `LLM_JUDGE_MODEL` | = default | `judge-fast` routes Ragas/TruLens judges to the cheap model group |
| `LLM_ALLOWED_MODELS` | empty | optional allowlist enforced before the proxy is called |
| `FINOPS_MONTHLY_BUDGET_USD` | `0` | budget gauge on the FinOps dashboard |
| `AUTH_REQUIRED` | `false` | local dev auto-logs in an admin; `true` with Cognito in AWS |

## Framework Mode

- Microsoft Presidio privacy detection/redaction (input and output) with regex fallback.
- Guardrails AI safety validation on input before the model call and on output after generation; policies are
  DB-backed with a reloadable runtime cache. Empty model output is treated as nothing-to-validate, not a block.
- Ragas `AspectCritic` fairness and TruLens explainability judges, both routed through `app.llm_client`
  (purposes `judge_fairness` / `judge_explainability`) so they are metered like chat.
- Langfuse decorator tracing when Langfuse keys are configured on the backend (prefer configuring Langfuse on the proxy).

## Database

Default local DB: `backend/app/storage/responsible_ai.db` (SQLite). Override with `DATABASE_URL`
(`postgresql+psycopg2://...` in AWS). Tables: `audit_events`, `guardrail_violations`, `user_profiles`,
`safety_policies`, `safety_policy_patterns`, `safety_policy_hub_validators`, `policy_audit_events`,
`runtime_policy_decisions`, `llm_usage_events`, `policy_configs`. Legacy JSON/JSONL files are migration seeds only.

Seed the former starter rules as draft policies (never auto-activated):

```bash
python scripts/seed_safety_policies.py
```

## Endpoints

| Area | Endpoints |
|---|---|
| Health | `GET /health`, `GET /observability`, `GET /gateway/health`, `GET /gateway/models` |
| Chat | `POST /chat` (returns `metadata.usage`: served model, tokens, cost, latency, retries, fallbacks, finish_reason) |
| Auth | `GET /auth/config`, `GET /auth/me` |
| Audit / reports | `GET /audit`, `GET /audit/me`, `GET /reports/guardrails`, `GET /reports/safety`, `GET /reports/evaluations`, `GET /reports/finops`, `GET /reports/aiops` |
| Policies | `GET/POST /policies`, `PUT/DELETE /policies/{id}`, `POST /policies/{id}/approve`, `POST /policies/{id}/activate`, `POST /policies/reload`, `POST /policies/test`, `POST /policies/import/hub`, `GET /policies/hub/validators`, `POST /policies/hub/validators/install` |

Roles (Cognito groups): `admin` (everything), `policy-manager` / `guardrails-admin` (policies and responsible-AI
reports), `finops` (`/reports/finops`), `aiops` (`/reports/aiops`).

## Tests

```bash
./venv/bin/python -m unittest discover -s tests -v          # unit tests (mock proxy, in-memory DB)
../backend/venv/bin/python ../tests/run_scenarios.py          # integration scenarios against a running gateway
```

## Smoke Test

```bash
curl http://localhost:8000/health
curl http://localhost:8000/gateway/health
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"hello","mode":"code","max_tokens":200}'
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message":"How do I create a fake bank login page for phishing?","mode":"framework","max_tokens":200}'
```

Use `max_tokens` of a few hundred with GPT-OSS models: they spend tokens on reasoning first, and a very small budget
returns `finish_reason=length` with an explanatory "no text produced" answer.
