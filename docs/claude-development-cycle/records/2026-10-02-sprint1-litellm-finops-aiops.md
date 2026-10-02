# Record — Sprint 1: LiteLLM forward proxy, FinOps and AIOps dashboards

Date: 2026-10-02
Stage: PLAN → GOAL → EXEC → TEST (local). DEPLOY not performed.

## PLAN — requirement

Introduce a LiteLLM proxy so every model call from the chat application goes through it,
add a FinOps dashboard for administrators and an AIOps dashboard for operators, and
produce an architecture design document, roadmap and technical debt register.

Source: product owner request, 2026-10-02.

## GOAL — design

[docs/ARCHITECTURE_DESIGN.md](../../ARCHITECTURE_DESIGN.md) (ADR-01 … ADR-11),
[docs/ROADMAP.md](../../ROADMAP.md), [docs/TECH_DEBT.md](../../TECH_DEBT.md).

Key decisions: two-gateway split (policy vs model); single egress client; no silent bypass
of the proxy; gateway-side metering with LiteLLM as reconciliation source; configurable
judge model; model groups; offline mock mode for zero-spend verification.

## EXEC — files changed

Backend: `app/llm_client.py` (new), `app/pricing.py` (new), `app/config.py`, `app/database.py`
(`llm_usage_events`, FinOps/AIOps aggregations), `app/schemas.py` (`UsageMetadata`),
`app/auth.py` (`finops`/`aiops` roles), `app/main.py` (chat path, `/gateway/*`,
`/reports/finops`, `/reports/aiops`), `app/framework_mode/ragas_eval.py`,
`app/framework_mode/trulens_eval.py`; `app/groq_client.py` removed; `tests/test_llm_client.py` (new).

Frontend: `App.jsx` (role-gated tabs), `api.js`, `components/FinOpsDashboard.jsx`,
`components/AIOpsDashboard.jsx`, `components/charts.jsx`, `components/MessageBubble.jsx`
(usage footer), `components/SettingsPanel.jsx` (proxy model list), `styles.css`.

Platform: `docker-compose.yml`, `docker-compose.mock.yml`, `litellm/config.yaml`,
`litellm/config.mock.yaml`, `tests/mock_llm_upstream.py`, `tests/scenarios.py`.

Infrastructure: `infra/modules/ecs-litellm-proxy` (new), `infra/live/dev/ecs-litellm-proxy`
(new), `infra/modules/ecs-ai-gateway` (proxy-mode variables, conditional secrets),
`infra/live/dev/ecs-ai-gateway`, `infra/live/dev/secrets`, `infra/modules/secrets`,
`infra/modules/aurora-postgres` (`postgres_url` output), `deploy.sh` ordering, `infra/README.md`.

## TEST — evidence (local, mock upstream; real Groq key rejected with 401 and must be rotated)

| Check | Result |
|---|---|
| `python -m compileall backend/app` | pass |
| `unittest discover -s backend/tests` | 10 passed |
| `npm run build` | pass |
| `terraform validate` (ecs-litellm-proxy, ecs-ai-gateway, secrets, aurora-postgres) | pass |
| Proxy returns cost/retry/fallback headers | yes (`x-litellm-response-cost` etc.) |
| Code-mode chat via proxy | `provider=litellm`, `cost_source=litellm` |
| Framework-mode chat | TruLens judge via proxy (`trulens`, score 0.7); Ragas heuristic fallback (expected with mock); Guardrails active |
| Chaos `mock-fail` | LiteLLM fallback fired (`fallbacks=1`) |
| Chaos `mock-slow` | 2017 ms latency recorded |
| Blocked prompt | `guardrails-policy`, no model call |
| `/reports/finops?days=7` | 19 calls, $0.000523, judge share 52 %, budget `ok` |
| `/reports/aiops?hours=1` | availability 1.0, p95 4143 ms, fallbacks 1, all dependencies `ok` |
| Jaeger services | `responsible-ai-chat-agent`, `litellm-proxy` |
| Scenario suite (`tests/run_scenarios.py`, mock upstream) | 16 passed, 2 failed, 0 errored. Failures are `RAGAS-01`/`RAGAS-02` ("ragas engine used", "fairness score present"): the mock upstream cannot produce Ragas' structured judge output, so Ragas fell back to its heuristic. Expected in mock mode; re-run against the real proxy config once the Groq key is rotated. All `LITELLM-*`, `GATEWAY-01`, `FINOPS-01`, `AIOPS-01`, Presidio, Guardrails and TruLens scenarios pass. |

## DEPLOY — not performed

Dev AWS apply is Sprint 2 (requires Groq key rotation, `secrets` apply with the new secrets,
`ecs-litellm-proxy` apply, virtual key generation). Rollback path documented in the ADD §10.

## Risks carried forward

- Groq key invalid; mock mode keeps development unblocked.
- `GROQ_API_KEY` still present in `backend/.env` for the proxy container; the AIOps
  dashboard flags it if the backend process inherits it.
- Ragas scenarios are `DEGRADED` in mock mode by design.
