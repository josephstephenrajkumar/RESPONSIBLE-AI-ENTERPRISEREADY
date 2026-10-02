# Responsible AI Gateway — Scenario Test Suite

Integration scenarios that exercise each responsible-AI framework wired into the
gateway, through the **real running backend**. Every scenario is sent to the live
`/chat` or `/policies/test` endpoint, so results are persisted as audit events and
appear in the frontend dashboards — this suite doubles as the way to populate those
dashboards with meaningful data.

These are deliberately **not** unit tests. Unit tests would mock the frameworks out
and prove nothing about whether Guardrails, Presidio, Ragas and TruLens are actually
loaded, configured and enforcing at runtime — which is precisely the failure mode
this project has hit repeatedly (validators registered in the database but never
installed; evaluators declared but silently falling back to heuristics).

## Contents

| File | Purpose |
|---|---|
| `scenarios.py` | Scenario definitions: prompt, target framework, and the checks applied to the response |
| `run_scenarios.py` | Runner that drives the live gateway, prints a report, and optionally writes JSON |
| `README.md` | This document |

## Prerequisites

1. **LiteLLM proxy running** (all model calls go through it):
   ```bash
   docker compose up -d
   ```
   For a zero-spend run, use the mock upstream instead of Groq:
   ```bash
   backend/venv/bin/python tests/mock_llm_upstream.py --port 4010 &
   docker compose -f docker-compose.yml -f docker-compose.mock.yml up -d litellm
   ```
   In mock mode `RAGAS-*` scenarios report `DEGRADED` (the mock cannot satisfy Ragas'
   output schema); `TRULENS-*`, `LITELLM-*`, `GATEWAY-*`, `FINOPS-*` and `AIOPS-*` pass.
2. **Backend running** (it is the gateway under test):
   ```bash
   cd backend && ./venv/bin/python3 -m uvicorn app.main:app --port 8000
   ```
3. **A working `GROQ_API_KEY`** in `backend/.env` (read by the proxy container) when not in
   mock mode. Ragas and TruLens are LLM-judged: without a working provider they fall back
   to heuristics and those scenarios report `DEGRADED` rather than `PASS`.
3. **Guardrails Hub validators installed** for the `GUARDRAILS-03` scenario — install
   them from the admin panel (Guardrails Hub Validators → Install) or they will report
   setup errors.

## Running

```bash
# full suite (from the repo root, using the backend virtualenv)
backend/venv/bin/python3 tests/run_scenarios.py

# only one framework
backend/venv/bin/python3 tests/run_scenarios.py --only RAGAS
backend/venv/bin/python3 tests/run_scenarios.py --only Presidio

# against a different gateway, with a JSON report
backend/venv/bin/python3 tests/run_scenarios.py --base-url http://localhost:8000 --json report.json

# against the AWS dev gateway (AUTH_REQUIRED=true): pass a Cognito id token for an admin user
backend/venv/bin/python3 tests/run_scenarios.py --base-url https://0nl4sfks87.execute-api.ap-southeast-1.amazonaws.com --token "$TOKEN"
```

Exit code is non-zero if anything `FAIL`s or `ERROR`s (`DEGRADED` does not fail the run).

**Expect the full suite to take 3–5 minutes.** Each framework-mode request runs local
ML inference (Presidio NER, Guardrails hub validators) plus up to three Groq calls
(the answer, the Ragas judge, the TruLens judge).

## Result statuses

| Status | Meaning |
|---|---|
| `PASS` | All checks passed |
| `DEGRADED` | The framework fell back to its heuristic path — usually the judge LLM or a validator was unavailable. The gateway behaved correctly (it degraded gracefully instead of erroring), but the real framework did not run |
| `FAIL` | A substantive check failed — the gateway did not behave as specified |
| `ERROR` | The request itself failed (gateway down, timeout) |

`DEGRADED` is separated from `FAIL` deliberately: a provider outage should not be
reported as a code defect, and a fallback should never be silently counted as a pass.

## Scenario coverage

### LiteLLM — model gateway

| ID | Scenario | Asserts |
|---|---|---|
| `LITELLM-01` | Plain chat question | `metadata.provider == 'litellm'`; served model, tokens and latency reported; `cost_source == 'litellm'` (metered by the proxy, not estimated locally) |
| `LITELLM-02` | Framework-mode question (triggers judge calls) | Chat call via proxy; `request_id` present so judge rows join to it in `llm_usage_events` |

### Presidio — privacy detection and redaction

| ID | Scenario | Asserts |
|---|---|---|
| `PRESIDIO-01` | Prompt containing synthetic name, email, phone and SSN | Presidio engine active; entities detected; input redacted **before** the provider call; privacy risk elevated |
| `PRESIDIO-02` | Benign finance question with no personal data | No findings and no redaction — guards against over-flagging |

### Guardrails — safety policy enforcement

| ID | Scenario | Asserts |
|---|---|---|
| `GUARDRAILS-01` | Dangerous-instructions prompt (weapon construction) | Request blocked; risk elevated; **no provider call made** (`provider: guardrails-policy`) |
| `GUARDRAILS-02` | Benign credit-risk question | Not blocked; Guardrails engine active; answer produced — guards against over-blocking |
| `GUARDRAILS-03` | PII-bearing text through `/policies/test` | Hub validators compile with **no setup errors**; real engine (not regex fallback); content flagged |
| `GUARDRAILS-04` | Jailbreak / prompt-injection attempt | Guardrails engine active; a policy version is resolved (policies actually loaded) |

### Ragas — LLM-judged fairness

| ID | Scenario | Asserts |
|---|---|---|
| `RAGAS-01` | Neutral, objective lending-criteria question | `evaluator_engine == 'ragas'` (not fallback); numeric score in 0–1; neutral answer judged fair (`1.0`) |
| `RAGAS-02` | Question touching a protected attribute (age) | Real Ragas engine used; score present; fairness risk classified |

### TruLens — LLM-judged explainability

| ID | Scenario | Asserts |
|---|---|---|
| `TRULENS-01` | Prompt explicitly requesting step-by-step reasoning | `evaluator_engine == 'trulens'` (not fallback); numeric score in 0–1; explanation level classified |
| `TRULENS-02` | Prompt demanding a bare one-word answer | Real TruLens engine used; score present — the contrast with `TRULENS-01` is what the Evaluation Dashboard trend visualises |

### Dashboard-facing aggregate checks

Run after the scenarios, so they assert on exactly the data the frontend will render.

| ID | Endpoint | Asserts |
|---|---|---|
| `DASHBOARD-01` | `/reports/evaluations` | Events recorded; **real** `ragas` and `trulens` engine counts > 0; averages computed |
| `DASHBOARD-02` | `/reports/guardrails` | Violation report returned |
| `DASHBOARD-03` | `/observability` | Tracing status and trace endpoint reported (drives the header badge) |
| `GATEWAY-01` | `/gateway/health` | Proxy mode, reachable, default model served, **application holds no provider key** |
| `FINOPS-01` | `/reports/finops?days=7` | Calls and spend recorded; `litellm` cost source; `chat` and `judge_*` purposes present; budget posture and unit economics computed |
| `AIOPS-01` | `/reports/aiops?hours=24` | Availability and p95 computed; LLM gateway and database dependencies `ok`; guardrail block stats present |

## Seeing the results in the UI

After a run, open the frontend (`http://localhost:5173`):

- **Admin screen → Evaluation Dashboard** — Ragas fairness and TruLens explainability
  averages, per-engine counts (real vs `heuristic_fallback`), risk/level distributions,
  and the daily trend. This is where the suite's statistics are most visible.
- **Admin screen → Governance Dashboard** — policy counts and lifecycle state.
- **Chat screen** — the per-message responsible-AI panel shows the same fields inline
  for any message you send yourself.

The dashboards aggregate the **last 200 framework-mode requests**, so scenario results
blend with any manual chatting you have done. The `by_engine` breakdown is the honest
signal: `ragas`/`trulens` counts are real LLM-judged evaluations, `heuristic_fallback`
counts are requests where the framework could not run.

## Test data policy

Every prompt in `scenarios.py` is synthetic. No real personal data, customer content,
credentials or secrets appear in this suite, in its output, or in the audit records it
generates — consistent with `docs/claude-development-cycle/04-test-verification.md`.
The "PII" used (`jane.doe@example.com`, `555-0134`, `123-45-6789`, `4111 1111 1111 1111`)
is deliberately well-known fake test data.

## Known failing scenario

`GUARDRAILS-03` currently **fails** its "no validator setup errors" check:

```
GroundedAIHallucination: No module named 'guardrails_ai.grounded_ai_hallucination'
```

This is accurate, not a flaky test. The `hub://guardrails/grounded_ai_hallucination`
validator no longer exists upstream — neither its Guardrails Hub page nor a
`guardrails-ai-grounded-ai-hallucination` PyPI package resolves (both 404). It has been
removed from the recommended catalog in `backend/app/guardrails_hub_catalog.py`, but a
policy referencing it still exists in the local database from before that change.

**To clear it:** delete the "Grounded AI Hallucination Hub Policy" in the admin panel's
Policy Registry. The scenario then passes.
