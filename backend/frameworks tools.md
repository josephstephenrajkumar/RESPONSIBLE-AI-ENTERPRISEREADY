# Responsible AI Framework Tools

This project supports two implementation modes:

- `code`: local Python checks for privacy, safety, fairness, explainability, verifiability, transparency, governance, and controllability.
- `framework`: framework-oriented integrations for observability, tracing, privacy, safety, and evaluation.

## Current Tooling Map

| Tool | Implementation Status | Purpose | Responsible AI Pillars |
| --- | --- | --- | --- |
| Langfuse | Implemented for framework-mode chat calls with `@observe` decorators | LLM trace, generation metadata, usage, answer visibility | Transparency, Governance |
| OpenTelemetry | Implemented for FastAPI, HTTPX, manual DB spans, optional SQLAlchemy instrumentation | Distributed tracing across API, LLM HTTP calls, and persistence | Transparency, Governance, Reliability |
| Jaeger | Implemented via local/Docker exporter target | Trace collection and visual inspection | Transparency, Operations |
| SQLAlchemy | Implemented with SQLite default and portable `DATABASE_URL` | Policy and audit persistence replacing JSON/JSONL runtime storage | Governance, Auditability |
| Presidio | Implemented in framework mode with regex fallback | PII detection and redaction before LLM calls and after LLM responses | Privacy |
| Guardrails AI | Implemented in framework mode with a local custom validator | Input/output safety validation, phishing/fraud/AML/cyber/harm policy blocking | Safety, Controllability |
| TruLens | Lightweight placeholder | LLM answer/explanation evaluation hook | Explainability, Verifiability |
| Ragas | Lightweight placeholder | RAG/fairness-style evaluation hook | Verifiability, Fairness |

## Implemented Backend Shape

```text
backend/app/
├── database.py                         # SQLAlchemy models, migration, DB helpers
├── telemetry.py                        # OpenTelemetry + Jaeger setup
├── framework_mode/
│   ├── langfuse_observability.py       # Langfuse decorators and context updates
│   ├── presidio_privacy.py
│   ├── guardrails_safety.py
│   ├── trulens_eval.py
│   └── ragas_eval.py
└── storage/
    ├── responsible_ai.db               # SQLite DB created at startup
    ├── audit_log.jsonl                 # legacy seed source only
    └── policy_config.json              # legacy seed source only
```

## Runtime Responsibilities

- `startup_event()` configures OpenTelemetry, instruments SQLAlchemy when available, creates DB tables, and migrates legacy JSON data once.
- `/chat` runs framework-mode privacy redaction before the LLM call.
- `/chat` runs Guardrails AI framework-mode safety validation before the LLM call and can return a policy-blocked response without calling the model.
- `/chat` writes audit events to SQLAlchemy, not JSONL.
- `/audit` reads recent audit events from SQLAlchemy.
- `/policy` reads governance policy from SQLAlchemy.
- `/observability` reports tracing status, Jaeger endpoint, Jaeger UI URL, and SQLAlchemy instrumentation status.

## Policy Metadata Status

The Guardrails AI safety policies are currently starter rules embedded in `backend/app/framework_mode/guardrails_safety.py` so the prototype can run without an external policy service. They are not downloaded automatically from Guardrails Hub, BIS/BCBS, MAS, or any regulator.

Production policy flow should be:

```text
external guidance or Guardrails Hub validators
  -> internal risk/compliance review
  -> approved versioned policy metadata
  -> runtime Guardrails configuration
  -> audit log records policy version and decision
```

## Production Upgrade Path

1. Replace SQLite with Postgres by setting `DATABASE_URL=postgresql+psycopg://...`.
2. Add Alembic migrations once the schema needs versioned production changes.
3. Run Jaeger or an OTLP collector outside the app container.
4. Move Guardrails AI safety rules into versioned policy metadata or database tables.
5. Add authentication and role-based access before exposing `/audit` in shared environments.
6. Replace remaining TruLens and Ragas placeholders with real framework calls when those pillars are expanded.
