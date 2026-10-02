# Requirements Record — Real Ragas + TruLens Integration

Date: 2026-09-07
Requested by: joseph.stephenr@gmail.com

```text
Request:
  Replace the scaffolded Ragas (fairness) and TruLens (explainability) evaluators in
  backend/app/framework_mode/ with real library-backed integrations, reusing the
  existing Groq credential as the judge LLM (no new secret/provider). Add a frontend
  evaluation dashboard surfacing the resulting scores/trends. Follow this repo's own
  PLAN->GOAL->EXEC->TEST->DEPLOY cycle, including code review, security review, local
  testing, and an explicit human approval gate before any AWS deployment action.

Owner and users:
  Owner: joseph.stephenr@gmail.com (repo owner / engineering manager role for this change).
  Users affected: any client calling the AI Gateway /chat endpoint in `framework` mode,
  and any admin user viewing the responsible-AI dashboards in the frontend.

Environment:
  Local development only for this change. No dev/stage/production environment is
  touched. AWS deployment is explicitly out of scope for the coding phase (see Non-goals).

In scope:
  - backend/app/framework_mode/ragas_eval.py: real Ragas-based fairness evaluator.
  - backend/app/framework_mode/trulens_eval.py: real TruLens-based explainability evaluator.
  - backend/app/main.py: await the two evaluator calls in the `framework` mode branch of /chat.
  - backend/app/database.py + a new GET /reports/evaluations endpoint: aggregate the new
    scores from existing audit_events for dashboard consumption.
  - frontend: new evaluation dashboard (admin screen) + inline message display upgrades.
  - backend/requirements.txt: add the real ragas/trulens dependencies.
  - Delivery-cycle artifacts under docs/claude-development-cycle/records/.

Out of scope (non-goals):
  - Any change to Guardrails, Presidio, Langfuse, auth, or policy-lifecycle logic.
  - Turning /chat into an asynchronous/background workflow — it stays a single
    synchronous request/response; only internal I/O calls become `await`-able.
  - Any RAG/retrieval step — Ragas metrics that require retrieved context (e.g.
    Faithfulness) do not apply here and will not be used.
  - Any Terraform/Terragrunt apply, image push, or AWS deployment command.
  - Full redesign of ResponsibleAIPanel.jsx (only new fields added, not rebuilt).

Functional requirements:
  - Framework-mode chat responses return real, non-hardcoded fairness and
    explainability scores (0-1 floats) computed by Ragas/TruLens via the Groq judge.
  - If the judge LLM call or library import fails, the endpoint must not 500 — it
    falls back to today's heuristic behavior with `evaluator_engine` marked accordingly.
  - A new GET /reports/evaluations endpoint returns aggregate stats (avg scores, risk
    distribution, time series) for the frontend dashboard, following the existing
    GET /reports/guardrails pattern and auth.
  - Frontend admin screen shows a real evaluation dashboard (not a raw JSON dump) for
    these two signals, plus a small inline upgrade to per-message display.

Non-functional requirements:
  - No new frontend dependency (charts hand-rolled in inline SVG) unless the user
    requests otherwise.
  - No new backend secret; the existing GROQ_API_KEY is reused.
  - Dependency additions are pure-Python (no new apt packages in backend/Dockerfile)
    unless the EXEC-time introspection of the chosen TruLens package finds otherwise.

Responsible-AI requirements:
  - The change touches two of the eight responsible-AI evaluators (fairness,
    explainability) covered by ResponsibleAIResponse; it must not weaken the other six.
  - Scores must be derived from an actual LLM-judged evaluation, not a static value.

Security and privacy constraints:
  - No raw prompt/answer text or credentials introduced into new audit/trace fields
    beyond what is already persisted today.
  - New /reports/evaluations endpoint must require the same authentication as the
    existing /reports/guardrails endpoint.

Data and audit impact:
  - No new database table. New score fields ride inside the existing
    audit_events.responsible_ai JSON blob (already persisted via append_audit_event).

Dependencies:
  - `ragas` (new).
  - TruLens current package(s) — exact package name(s) to be confirmed during EXEC via
    isolated `pip install` + introspection, since the TruLens package layout has
    changed across versions.

Acceptance criteria:
  - A framework-mode /chat call returns real (non-static) fairness_score and
    explainability_score fields sourced from Ragas/TruLens.
  - Forcing the judge-LLM path to fail (e.g. missing key) still returns a 200 with
    fallback values, not a 500.
  - GET /reports/evaluations returns aggregated data matching what was persisted.
  - `python -m compileall backend/app` and `npm --prefix frontend run build` both pass.
  - Frontend dashboard visibly renders non-placeholder scores after a real chat call.

Rollback or recovery:
  - Revert the feature branch commits; no data migration was performed, so rollback
    is a pure code revert with no cleanup needed.

Allowed actions:
  - Code, documentation, and dependency-manifest changes. No infrastructure apply,
    no image push, no AWS CLI/Terraform mutation.

Open questions:
  - Exact TruLens package/API surface to target (resolved during EXEC via
    introspection, not guessed from memory) — see Design Record.
```

## PLAN Gate

Approved by joseph.stephenr@gmail.com via the plan-mode review on 2026-09-07 (judge LLM = reuse Groq; frontend scope = full dashboard; branch name = `feature/real-ragas-trulens-eval`). No security or policy decision remains open — the only open item (TruLens package selection) is a technical implementation detail with no security/policy dimension, resolved in EXEC via introspection rather than a hidden assumption.
