# DEPLOY Preconditions Checklist — Real Ragas + TruLens Integration

Date: 2026-09-08
Prepared by: Claude, for review by the human release owner (joseph.stephenr@gmail.com)

This document is guidance and a status checklist only. Preparing it does not
authorize or execute any deployment — per this repository's own DEPLOY gate,
Claude has not run, and will not run, any `terragrunt apply`, image push, or AWS
CLI mutation. Everything below is either already true (checked) or requires the
release owner's decision (unchecked, with the open question stated).

## What changed

- Real Ragas (`AspectCritic`) and TruLens (`LLMProvider`/`generate_score`) LLM-judged
  evaluators replacing the previous regex/hardcoded stubs, judged by the existing
  Groq deployment (no new provider, no new secret).
- New `GET /reports/evaluations` endpoint (admin-only, same `require_policy_manager`
  gate as other admin endpoints) aggregating fairness/explainability scores from the
  existing `audit_events` table — no new database table.
- New frontend "Evaluation Dashboard" panel in the admin screen.
- `backend/requirements.txt`: added `ragas`, `langchain-community<0.4` (required pin
  — see Design Record's EXEC-time API confirmation), `trulens-core`, `trulens-feedback`.
- Two doc corrections in `docs/RESPONSIBLE_AI_DESIGN.md` (Ragas/TruLens were
  documented as placeholders; now documented as real integrations).
- One unrelated local `.env` fix (`GROQ_API` renamed to `GROQ_API_KEY` to match
  `config.py`/`.env.example`/the ECS task definition) — local-only, not part of any
  committed change, mentioned here only because it affects whether local testing
  could exercise the live judge-LLM path (see Evidence Record section 4).

## Separate issue found, intentionally not fixed here

The default `GROQ_MODEL` (`llama-3.3-70b-versatile`, set in `.env.example` and the
Terraform `groq_model` variable) has been removed from Groq's current model catalog
— any deployment still using it will get `groq-error`/404 on every chat request,
independent of this PR. Confirmed via a live `GET /v1/models` call. This predates
this change and affects the primary chat path, not just fairness/explainability, so
picking a replacement default model is a product decision for the release owner,
not something this PR should decide unilaterally.

## Preconditions

- [ ] **Target AWS account/profile/region/environment** — not yet specified by the
      release owner. `infra/live/dev/` is the only environment currently defined in
      this repo; confirm `dev` is the intended target before anything proceeds.
- [x] **Change is tested** — see Evidence Record
      (`docs/claude-development-cycle/records/2026-09-07-evidence-record.md`):
      full app import, `/chat` framework-mode end-to-end, `/reports/evaluations`
      aggregation, auth parity, frontend build, and a live Playwright screenshot all
      pass. The judge-LLM-scored path was confirmed both with the network boundary
      mocked (section 1) and end-to-end against the live Groq API with real,
      non-fallback `ragas`/`trulens` scores (section 4) — using a currently-valid
      Groq model via an env override, since the repo's default `GROQ_MODEL` has been
      removed from Groq's catalog (pre-existing, unrelated to this change).
- [ ] **Change is approved** — code review and security review both ran with no
      unresolved findings (one authz gap found and fixed pre-merge; see below), but
      formal sign-off on the PR itself is still the release owner's decision.
- [x] **Secrets exist only in approved stores** — no new secret was introduced.
      `GROQ_API_KEY` continues to flow through Secrets Manager into the ECS task
      exactly as before (`infra/modules/ecs-ai-gateway/main.tf`).
- [x] **Database migrations / backward compatibility understood** — no schema
      change. New fields ride inside the existing `audit_events.responsible_ai` JSON
      column; `_ensure_sqlite_columns()`/Postgres schema are untouched.
- [ ] **Infrastructure plans reviewed, no unexpected destruction** — not applicable
      yet: no Terraform/Terragrunt files were touched by this change, so no new plan
      exists to review. The only infra-adjacent consideration is the backend Docker
      image growing (new pure-Python dependencies: `ragas`, `trulens-core`,
      `trulens-feedback`, and their transitive deps — pandas, sqlalchemy, alembic,
      scikit-learn, scipy, nltk, langchain_core, etc.) — recommend the release owner
      spot-check the built image size/cold-start before relying on current ECS task
      CPU/memory sizing (`infra/modules/ecs-ai-gateway`), since this wasn't load-tested.
- [x] **Backend image / frontend artifact traceability** — standard: whatever
      commit is merged and tagged is what `docker build` / `vite build` will produce;
      no build-script changes were made.
- [ ] **Rollback, monitoring, incident contacts ready** — rollback is a plain code
      revert (no data migration to unwind — see Requirements Record), but confirming
      monitoring/on-call readiness is the release owner's call, not Claude's.
- [x] **Governance approval for responsible-AI policy changes** — not applicable:
      this change does not alter Guardrails policy logic, policy lifecycle, or any
      governed policy state; it only replaces two evaluator implementations and adds
      a read-only reporting endpoint.

## Review results referenced above

- **Code review**: 2 findings, both fixed — (1) `/reports/evaluations` was missing
  the `require_policy_manager` authorization dependency used by every other
  admin-facing endpoint; (2) a `daily_series.sample_count` field could silently
  report the wrong metric's count when fairness/explainability null-rates diverged
  (split into two explicit fields instead).
- **Security review**: no HIGH/MEDIUM findings outstanding (the authz gap above was
  already fixed before this pass ran).

## Project Release Order

Not started. Per this repo's DEPLOY doc, deployment would follow: network → secrets
→ cognito → aurora-postgres → ecr → build/push backend image → ecs-ai-gateway →
api-gateway → frontend-s3-cloudfront → observability, with each module's Terraform
plan reviewed before apply. None of this has been run.

## Request

This checklist is ready for the release owner's review. **Claude is not deploying
anything and is waiting for an explicit go/no-go decision** on: (1) target
environment, (2) formal change approval, and (3) whether to proceed to preparing
(not applying) the AWS deployment steps.
