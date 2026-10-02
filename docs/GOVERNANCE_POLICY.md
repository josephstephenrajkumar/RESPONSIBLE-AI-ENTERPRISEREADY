# Governance Policy

## Policy Scope

The application enforces governance across:

- user request handling
- model provider access
- Responsible AI evaluation
- audit event persistence
- trace and observability metadata
- model provider access through the LiteLLM proxy
- cost attribution and operational review (FinOps / AIOps dashboards, Jaeger/X-Ray, Langfuse)

## Storage Policy

Runtime governance data is stored in SQLAlchemy tables:

- `policy_configs`: active policy payload
- `audit_events`: request-level audit events (user-scoped)
- `guardrail_violations`: per-violation records
- `safety_policies`, `safety_policy_patterns`, `safety_policy_hub_validators`, `policy_audit_events`, `runtime_policy_decisions`: policy governance
- `llm_usage_events`: one row per model call (tokens, cost, latency, retries, fallbacks, status, tenant/user/purpose); contains no prompt or completion text

Legacy files are retained only as migration seed sources:

- `backend/app/storage/policy_config.json`
- `backend/app/storage/audit_log.jsonl`

New runtime writes go to the database configured by `DATABASE_URL`.

## Audit Policy

Each chat request stores:

- `request_id`
- timestamp
- mode: `code` or `framework`
- model
- provider
- cache flag
- answer summary
- full Responsible AI pillar assessment

The `/audit` endpoint returns recent events and should be protected by authentication before production exposure (TD-08). `/audit/me` and the `/reports/*` endpoints are role-gated.

## Observability Policy

OpenTelemetry traces are exported to Jaeger for backend API, HTTP client, and DB workflow visibility. Framework-mode LLM calls also use Langfuse decorator tracing.

Required production controls:

- avoid storing secrets in trace attributes
- use request IDs for correlation
- configure retention in Jaeger or the OpenTelemetry backend
- restrict Jaeger and audit access to authorized operators

## Responsible AI Policy

Every response includes assessments for:

- privacy
- safety
- fairness
- explainability
- verifiability
- transparency
- governance
- controllability

Current framework status:

- Presidio is implemented for privacy detection/redaction with regex fallback.
- Guardrails AI is implemented for safety validation and policy blocking; empty model output is not treated as a violation.
- Ragas (fairness) and TruLens (explainability) are implemented as LLM judges routed through the LiteLLM proxy and metered as `judge_*` purposes.
- All model calls leave the application through the LiteLLM proxy; the application tier holds no provider credential in `proxy` mode.

## Model Access, Cost and Operations Policy

- Provider credentials live only in the LiteLLM proxy (Secrets Manager → proxy task). The gateway uses a LiteLLM key scoped to the models and budget it needs.
- Every model call is attributed to user, tenant, client, agent and purpose and metered for cost; the FinOps dashboard (`finops`/`admin` roles) is the review surface and LiteLLM key/team budgets are the enforcement point.
- Availability, latency, error classes and dependency health are reviewed on the AIOps dashboard (`aiops`/`admin` roles); CloudWatch alarms cover ECS CPU, log errors, proxy 5xx and unhealthy hosts.

## Safety Policy Source

Guardrails AI safety rules are database-backed policies with a draft → approved → active lifecycle, plus a small set of built-in dangerous-instruction patterns in application code. They cover categories such as phishing/fraud, AML evasion, cyber abuse, violence/harm, and unsafe financial actions.

These rules are not automatically updated from Guardrails Hub, BIS/BCBS, MAS, or any online regulator source. Production governance should move safety rules into approved versioned metadata or database-backed policy configuration.

Recommended production flow:

```text
external standards and validator catalogs
  -> risk/compliance review
  -> approved policy version
  -> runtime Guardrails configuration
  -> audit log with policy version and decision
```
