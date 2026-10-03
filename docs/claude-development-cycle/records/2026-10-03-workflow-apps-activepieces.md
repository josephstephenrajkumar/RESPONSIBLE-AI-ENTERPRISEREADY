# Requirements and Design Record — Workflow Apps on Activepieces

Date: 2026-10-03
Requested by: repo owner (chat request, 3 October 2026)

```text
Request:
  Review the Activepieces checkout (activepieces-main, read-only) as enterprise/solution architect and
  integrate it into the front end: (1) the existing chat app re-implemented on Activepieces, (2) a UI tool
  to build and publish new workflow apps whose AI inference goes through the LiteLLM proxy while other API
  calls go direct and bypass Responsible AI processing, (3) build the components in this repository,
  (4) review and update frontend, backend and database, (5) do not touch docs/AI platform,
  (6) test end to end and wait for the deploy instruction.

Owner and users:
  Owner: repo owner. Users: administrators with manage_workflows (admin, workflow-admin, model-admin);
  end users of published chat apps; FinOps viewers (workflow spend appears in the dashboards).

Environment:
  Local (docker compose + native gateway). AWS deployment designed (docs/ACTIVEPIECES_INTEGRATION.md 5.5)
  but not applied; waits for the deploy instruction.

In scope:
  workflows/pieces (two custom pieces, bundler), docker-compose activepieces service,
  backend: activepieces_client.py, workflow_tokens.py, workflow_templates.py, workflow_apps.py, auth.py
  (app tokens, manage_workflows), main.py (router, startup, /auth/me, /chat attribution), config.py,
  frontend: WorkflowApps.jsx, api.js, App.jsx, styles.css,
  tests: backend/tests/test_workflow_apps.py, tests/workflow_apps_e2e.py,
  docs: ACTIVEPIECES_INTEGRATION.md, workflows/README.md, README, QUICK_START.

Out of scope (non-goals):
  Modifying activepieces-main; Activepieces enterprise features (SSO embedding, API keys, piece sets);
  Terraform for the engine (designed only); changes under docs/AI platform.

Functional requirements:
  F1 Chat app as a workflow: template responsible-ai-chat, Chat UI trigger -> gateway /chat -> reply.
  F2 Workflow Apps screen: status/bootstrap, create from template, embedded builder, publish, enable/disable,
     runs, embedded chat, gateway-side test chat, delete, usage sync.
  F3 AI inference from workflow apps goes to the LiteLLM proxy (custom piece with per-app virtual key, and the
     engine AI provider pointed at the proxy); non-AI steps call their targets directly.
  F4 Control plane in the gateway with per-app LiteLLM key (budget) and gateway app token (hashed at rest).
  F5 Workflow spend ingested into llm_usage_events (purpose=workflow) for FinOps/AIOps.

Non-functional requirements:
  No secrets in the repository; credentials only as hashes in the gateway database and encrypted in the engine.
  Tenancy enforced by the gateway registry. Idempotent bootstrap. Unit tests without external services.

Responsible-AI requirements:
  Governance is explicit per step: only the Responsible AI Gateway piece passes through the pipeline; direct
  proxy calls are visible in FinOps as purpose=workflow and carry the app attribution.

Security and privacy constraints:
  App tokens authenticate as the app (group workflow-app) and cannot reach admin routes; the public chat page is
  reachable by flow id (upstream design) and must sit behind the gateway or a proxy on the internet.

Acceptance criteria:
  backend unit suite green; tests/workflow_apps_e2e.py PASS against the local stack (bootstrap, both templates
  publish and answer, usage sync, token boundary); frontend builds.

Rollback or recovery:
  Remove the activepieces compose service and the Workflow Apps tab; tables workflow_apps, workflow_settings and
  workflow_app_tokens are additive and can be dropped. Keys issued to apps are deleted on app deletion.

Allowed actions:
  Code, docs, local run and tests. No AWS apply, no image push, no deployment.

Open questions:
  Enterprise licence for embedding SSO and per-tenant projects (BACKLOG candidate); hosting the chat page behind
  the gateway before internet exposure.
```
