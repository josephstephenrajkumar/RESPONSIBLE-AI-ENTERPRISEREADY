# Activepieces Integration: Review and Architecture for Workflow Apps

| | |
|---|---|
| Status | Implemented, verified locally and deployed to dev AWS 2026-10-03 (section 10; snapshot addendum in `docs/aws-snapshots/`) |
| Scope | Embedding the Activepieces workflow builder in the Responsible AI Enterprise Gateway front end, re-implementing the chat app as a workflow, and letting administrators build and publish new workflow apps whose AI calls go through the LiteLLM proxy |
| Inputs | Read-only review of `activepieces-main` (version 0.92.0, 733 community pieces) and of this repository (frontend, backend, database, tests) |
| Related | [ARCHITECTURE_DESIGN.md](ARCHITECTURE_DESIGN.md), [LITELLM_PROXY_MANAGER.md](LITELLM_PROXY_MANAGER.md), [MULTI_TENANCY_DESIGN.md](MULTI_TENANCY_DESIGN.md), [NO_SECRETS_IN_GIT.md](NO_SECRETS_IN_GIT.md), [BACKLOG.md](BACKLOG.md) |

## 1. Executive summary

Activepieces is a sound choice as the workflow and app-builder layer for this platform, with one important
constraint: the features that make embedding seamless for an enterprise (SDK embedding with single sign-on,
API keys, per-project piece restrictions, audit log, project roles) are enterprise-licensed. The community
edition (MIT) still gives us everything needed for a working, governed integration:

- a public, login-free **chat UI** per published flow and a public synchronous webhook behind it,
- an **AI provider** abstraction that accepts an OpenAI-compatible base URL, so every "universal AI" step can be
  pointed at the **LiteLLM proxy**,
- **custom pieces** installable through the API as self-contained archives, which lets us ship a *Responsible AI
  Gateway* piece (governed chat) and a *LiteLLM Proxy* piece (direct inference) from this repository,
- a server that allows its UI to be **iframed** by an allow-listed origin.

The architecture therefore runs Activepieces as a separate service beside the gateway and the proxy. The gateway
owns the control plane (app registry, per-app credentials, templates, publish, usage ingestion) and the React front
end gains a **Workflow Apps** screen that embeds the Activepieces builder and chat UI. The chat app ships as a
workflow template whose only AI step is the Responsible AI Gateway piece, so privacy, safety, evaluation and
metering stay exactly where they are today. Apps built by administrators use the LiteLLM proxy for inference and
call other APIs directly, as required.

The enterprise licence remains the recommended upgrade for production customers who need SSO into the builder,
per-tenant projects and piece governance. Section 8 lists what changes when it is purchased.

## 2. What Activepieces is (as reviewed)

| Aspect | Finding |
|---|---|
| Version | 0.92.0 (`package.json`), image `activepieces/activepieces:0.92.0` on Docker Hub (2026-09-24). The `latest` tag is stale at 0.82.0 and must not be used |
| Licence | MIT, except `packages/ee/` and `packages/server/api/src/app/ee/` (Activepieces Enterprise Licence). Some modules under `app/ee` are registered even in the community edition (`platformProjectModule`, agent runs); we avoid them |
| Editions | `AP_EDITION` = `ce` (default), `ee`, `cloud`. Plan flags for CE are hard-coded in `OPEN_SOURCE_PLAN`: `embeddingEnabled false`, `aiProvidersEnabled true`, `managePiecesEnabled false`, `apiKeysEnabled false`, `ssoEnabled false`, `auditLogEnabled false`, `billedTeamProjectsLimit 1` |
| Runtime | Node 24 in the image; single container runs API + worker + UI on port 80. Postgres + Redis in production; PGlite + in-memory queue for development. Bun installs piece packages into a sandbox workspace at run time |
| API | Fastify, Zod schemas, all under `/api/v1`. Auth is a 7-day HS256 user JWT from `POST /v1/authentication/sign-in`. API keys are enterprise-only |
| Data model | platform → project → flow → flow_version (trigger tree as JSON) → flow_run. Users are per platform; every user owns a PERSONAL project; CE allows one TEAM project. Connections are encrypted (`app_connection.value`) and referenced from steps as `{{connections['externalId']}}` |
| Chat | Piece `@activepieces/piece-forms`, trigger `chat_submission` (webhook; emits `sessionId`, `message`, `files`), action `return_response` (markdown). UI route `/chats/{flowId}` is public; messages go to `POST /api/v1/webhooks/{flowId}/sync` (public, JSON or multipart `chatId` + `message`) |
| AI | Platform-level AI providers (`/api/v1/ai-providers`, platform admin). `provider: custom` accepts `{apiKeyHeader, baseUrl, models[], defaultHeaders}`; the worker builds the model with `createOpenAICompatible` and sends `[apiKeyHeader]: apiKey`. The universal AI piece executes through the server, never directly from the sandbox |
| Custom pieces | `POST /api/v1/pieces` with `packageType ARCHIVE`, `scope PLATFORM` (platform admin, works in CE). The worker extracts metadata by installing the tarball with bun and scanning exports for `constructor.name === 'Piece'`. Private npm registries are not supported (registry URL is hard-coded); REGISTRY pieces always come from npmjs |
| Piece build | Official pieces are published as one minified CommonJS bundle with every dependency inlined (esbuild, `keepNames`). The piece framework used by 0.92.0 (`@activepieces/pieces-framework` 0.40.0, `core-piece-types`, `core-utils`) is **not on npm** (npm stops at framework 0.32.0, June 2026), so custom pieces must be bundled from the checkout's sources |
| Embedding | Enterprise only: `managedAuthnModule`, signing keys and the embed SDK need `embeddingEnabled`. The CE server does send `Content-Security-Policy: frame-ancestors 'self' <origins>` from `AP_ALLOWED_EMBED_ORIGINS`, so an allow-listed origin can iframe `/chats/{flowId}` and the builder; the builder still asks for an Activepieces login |
| Security headers | No X-Frame-Options; CORS `*` on the API; no nginx in the image |
| Telemetry | On by default (`AP_TELEMETRY_ENABLED`), disabled in our compose file. Piece catalogue sync (`AP_PIECES_SYNC_MODE=OFFICIAL_AUTO`) calls cloud.activepieces.com; set `NONE` for air-gapped deployments and install pieces as archives |

## 3. Integration options considered

| Option | Description | Verdict |
|---|---|---|
| A. Fork the Activepieces UI into our React app | Vendor `packages/web` and mount the builder as a component | Rejected. 0.92.0 is a bun/turbo monorepo with its own routing, state, sockets and i18n; the fork would diverge within weeks and the checkout is read-only by requirement |
| B. Enterprise embed SDK | `activepieces.configure({ instanceUrl, jwtToken })` with signed provisioning tokens, per-tenant projects, hidden navigation | Correct long-term answer, needs a licence and licence activation against Activepieces' console. Designed for, not implemented (section 8) |
| **C. Separate service + control plane in the gateway + iframe (first delivery 2026-10-03, replaced by E the same day)** | Activepieces runs beside the gateway. The gateway signs in with a service account, installs our pieces, configures the AI provider, creates and publishes flows from templates, issues per-app credentials and ingests spend. The front end iframes the chat UI and the builder from an allow-listed origin | Works in CE with no forked code; everything we add lives in this repository; the upgrade to B is additive |
| D. Link-out only | Buttons that open Activepieces in a new tab | Fallback inside C for browsers that block third-party storage in iframes |
| **E. Separate service + control plane in the gateway + our own Workflow Studio (current)** | The engine is an internal backend with no public URL. The portal's Workflow Studio (`frontend/src/studio/`) builds, tests, publishes and inspects flows through the gateway's allow-listed Studio API (`backend/app/workflow_studio.py`); the engine's UI, origin and login never appear | Chosen after the review of C ([WORKFLOW_STUDIO_PLAN.md](WORKFLOW_STUDIO_PLAN.md), Track 2): the portal must look and behave as one product, and CE cannot re-theme or SSO-embed the engine UI |

## 4. Target architecture

```text
Browser (React, :5173)                                    Activepieces (:8080, CE 0.92.0)
  Chat | Responsible AI | Proxy Manager | FinOps | AIOps     API + worker + UI, PGlite/Postgres
  Workflow Studio ──── /workflows/apps/{id}/studio/* ───────► gateway → engine API (flows, pieces, connections, runs)
  App chat ─────────── /workflows/apps/{id}/chat ───────────► gateway → engine sync webhook (no public chat page)
        │                                                        │ flows run in the worker
        ▼ Bearer Cognito JWT                                      │
FastAPI gateway (:8000)                                           │  piece: Responsible AI Gateway
  /workflows/*  control plane  ──── service-account JWT ─────────►│    POST {gateway}/chat (app token)
  /chat         + app-token auth ◄────────────────────────────────┘  piece: LiteLLM Proxy
  /reports/*    + workflow usage ingestion                            POST {proxy}/chat/completions (virtual key)
        │                                                          universal AI piece → AP server → custom provider
        ▼ virtual key                                                              │
LiteLLM proxy (:4000) ◄────────────────────────────────────────────────────────────┘
  budgets, routing, spend log, provider keys           Groq / Bedrock / ...
```

Three call paths exist for a workflow app, by design:

| Path | Used by | Governance | Metering |
|---|---|---|---|
| Responsible AI Gateway piece → gateway `/chat` | the chat app template and any step that must be governed | full pipeline (Presidio, Guardrails, Ragas, TruLens, policies, audit) | `llm_usage_events` directly, attributed `client_id = workflow-app:<id>` |
| LiteLLM Proxy piece → proxy `/chat/completions` with the app's virtual key | app steps that need raw inference | proxy guardrails, budget and model scope of the key; no Responsible AI pipeline | proxy spend log, ingested into `llm_usage_events` by the gateway's usage sync |
| Universal AI piece → Activepieces server → custom provider → proxy | low-code AI steps (ask AI, summarise, extract) | proxy guardrails and the platform key's budget; no Responsible AI pipeline | proxy spend log under the platform key, tagged `workflow-apps` |

Non-AI steps (HTTP, data, SaaS pieces) run in the worker and call their targets directly. This satisfies the
requirement that only AI inference is routed through the proxy and nothing else passes through Responsible AI
processing unless the builder chooses the gateway piece.

## 5. Components built in this repository

### 5.1 Custom pieces (`workflows/pieces/`)

Two pieces, authored in TypeScript against the framework sources of the read-only checkout and bundled by
`build.mjs` exactly as the official CLI does (esbuild, CommonJS, Node 20 target, minified with `keepNames`, all
dependencies inlined, published package has `dependencies: {}`). The checkout is never modified; the build resolves
`@activepieces/*` imports by alias to its `packages/*/src` folders and installs the few third-party packages those
sources need into `workflows/pieces/node_modules`.

| Piece | Package | Auth (stored encrypted in Activepieces) | Actions |
|---|---|---|---|
| Responsible AI Gateway | `@responsible-ai/piece-responsible-ai-gateway` | gateway URL + workflow app token (`rai_app_...`) | `chat` (message, mode, model, temperature, max tokens, session, agent) returns the full `/chat` response; `list_models` |
| LiteLLM Proxy | `@responsible-ai/piece-litellm-proxy` | proxy URL + virtual key | `chat_completion` (model, system prompt, prompt, temperature, max tokens, JSON mode, app id, user) tags the call `purpose:workflow` and `client_id:workflow-app:<id>`; `list_models` |

Each bundle is about 360 KB. `npm run build` produces `dist/*.tgz`; the gateway installs them at bootstrap through
`POST /api/v1/pieces`.

### 5.2 Gateway control plane (`backend/app/`)

| Module | Responsibility |
|---|---|
| `activepieces_client.py` | Typed async client for the Activepieces API: sign-up on first boot, sign-in with cached 7-day token and re-login on 401, piece install, piece metadata, AI provider upsert, connection upsert, flow create / import / operation / publish / status / delete, run listing, synchronous chat webhook |
| `workflow_tokens.py` | Workflow app tokens: `rai_app_<random>` issued once, stored as SHA-256 hash with the app id and tenant. `authenticate_app_token()` is used by `auth.get_current_user` |
| `workflow_templates.py` | Flow templates as Python builders: `responsible-ai-chat` (Chat UI → Responsible AI Gateway chat → Respond on UI) and `litellm-chat` (Chat UI → LiteLLM chat completion → Respond on UI). Piece versions are resolved from the live catalogue at creation time |
| `workflow_apps.py` | The `/workflows` router (first `APIRouter` in the project): status and bootstrap, app CRUD, publish, enable/disable, runs, gateway-side chat proxy, usage sync. Owns the `workflow_apps` table |
| `auth.py` | Accepts workflow app tokens in addition to Cognito JWTs; new `manage_workflows` permission (`admin`, `workflow-admin`, `model-admin` groups) |
| `main.py` | Includes the router, creates the tables, starts bootstrap and the usage sync loop, exposes `manage_workflows` in `/auth/me`, attributes app-token calls on `/chat` |

Bootstrap (idempotent, runs at startup when `ACTIVEPIECES_ENABLED=true` and on `POST /workflows/bootstrap`):

1. Sign in the service account; on a fresh instance sign up, which makes it the platform admin.
2. Install the two archives from `ACTIVEPIECES_PIECES_DIR` if the catalogue lacks them or has an older version.
3. Issue (once) a LiteLLM virtual key `workflow-apps-platform` and upsert the custom AI provider "LiteLLM Proxy
   (Responsible AI)" with `baseUrl = ACTIVEPIECES_LITELLM_URL`, header `Authorization: Bearer <key>`, default header
   `x-litellm-tags: workflow-apps`, and the chat models allowed by the gateway as its model list.

Creating an app (`POST /workflows/apps`):

1. Insert the registry row (tenant, owner, name, template, status `draft`).
2. Issue a LiteLLM virtual key `wfapp-<id>` with the requested budget, model scope and metadata; store only its hash.
3. Issue a workflow app token; store only its hash.
4. Upsert two Activepieces connections (gateway piece and LiteLLM piece) carrying the plaintext credentials; they are
   encrypted at rest by Activepieces and never written to our database or logs.
5. Create the flow (`externalId = app id`, metadata with tenant and app id) and import the template.
6. Return the app with `builder_url` and `chat_url`.

Publishing is `LOCK_AND_PUBLISH`; disable/enable is `CHANGE_STATUS`. Deleting an app deletes the flow, both
connections, the virtual key and the token.

### 5.3 Front end: Workflow Apps and the Workflow Studio

`frontend/src/components/WorkflowApps.jsx` (permission `manage_workflows`): engine status (collapsed by default),
template gallery and create form, the app table (Open Studio, Publish, Disable/Enable, Delete), the Studio catalogue
dialog (which pieces builders may use) and spend sync. Nothing on the screen points at the engine.

`frontend/src/studio/` is the **Workflow Studio**, our own builder over the engine API through the gateway:

- `WorkflowStudio.jsx`: step tree with router branches and loop bodies, "+" insertion points (after, inside branch,
  inside loop), step editor (display name, piece properties, connection picker, error handling, skip, duplicate,
  delete), Code step editor, Router condition editor (OR groups of AND conditions, add/delete branch), Loop items,
  trigger sample data, step test (engine TESTING run polled to completion, input/output/error shown), versions with
  "use as draft", publish/enable, rename, and the app's chat window.
- `PropertyForm.jsx`: renders any piece property map (text, number, checkbox, static and dynamic dropdowns, dynamic
  property groups, object, array, JSON, markdown) with a data picker that inserts `{{step['output']['field']}}`
  expressions from recorded samples and test outputs.
- `StepPicker.jsx` (curated catalogue, actions and triggers, Code/Router/Loop), `ConnectionDialog.jsx` (custom auth,
  secret, basic auth, OAuth2 through the portal's `/oauth/callback` page and a popup), `RunsPanel.jsx` (run list,
  per-step input/output, retry from the failed step), `flowModel.js` (step shapes and operation payloads).
- `components/ui/index.jsx` and `theme.css`: shared primitives and design tokens so the Studio and the rest of the
  portal share one look; the Activate brand is applied by filling the `[data-theme="activate"]` block.

The gateway side is `backend/app/workflow_studio.py` (section 5.2 lists the routes). Only operations the Studio needs
are allow-listed; publish, status and deletion stay on the app routes so budgets, keys and tenancy are enforced once.
The existing Chat tab is unchanged; the `responsible-ai-chat` template reproduces it as a workflow that the Studio can
extend.

### 5.4 Data model

`workflow_apps` (SQLAlchemy on the shared `Base`, created with `ensure_tables()` like `gateway_settings`):

| Column | Purpose |
|---|---|
| `id` (string, pk) | short id, also used as Activepieces `externalId` and in `client_id = workflow-app:<id>` |
| `tenant_id`, `owner_user_id`, `owner_email` | ownership, from the creating user |
| `name`, `description`, `template`, `rai_mode`, `model` | definition |
| `ap_flow_id`, `ap_project_id`, `ap_connection_gateway`, `ap_connection_litellm` | Activepieces references |
| `litellm_key_alias`, `litellm_key_hash` | LiteLLM virtual key (hash only) |
| `monthly_budget_usd` | budget passed to the key |
| `status` (`draft`, `published`, `disabled`), `published_at`, `created_at`, `updated_at` | lifecycle |

`workflow_app_tokens`: `token_hash` (pk), `app_id`, `tenant_id`, `created_at`, `revoked_at`.

Usage ingestion writes into the existing `llm_usage_events` with `purpose = workflow`, `mode = workflow`,
`gateway_mode = proxy-direct`, `client_id = workflow-app:<id>`, `call_id = <proxy request id>` (deduplicated), so the
FinOps and AIOps dashboards show workflow spend without schema changes.

### 5.5 Deployment

Local: `docker compose up -d` also starts `activepieces` (image 0.92.0, PGlite, in-memory queue). Port 8080 is
published only so the natively running gateway can reach the engine; users never open it. `AP_FRONTEND_URL` points
at the engine itself because the worker fetches piece bundles from it. Secrets (`AP_ENCRYPTION_KEY`, `AP_JWT_SECRET`,
`ACTIVEPIECES_SERVICE_PASSWORD`) have dev-only defaults or live in the gitignored `backend/.env`.

AWS dev: module `ecs-activepieces` (one Fargate task behind an **internal** ALB, shared Aurora database over SSL,
in-memory queue, secrets in Secrets Manager; see TD-32 for the prod shape). Nothing uses the engine's public endpoint
any more; the HTTP API `api-gateway-workflows` of the first delivery is gone and its module was removed from the repo on
2026-10-05, the day the whole dev environment was torn down (see the snapshot addendum). The gateway task gets
`ACTIVEPIECES_API_URL` on the internal ALB and ships the piece archives in its image (`/app/pieces`).

### 5.6 AWS pieces (`workflows/pieces/aws-*`)

Four custom pieces give workflow apps AWS-native capabilities without storing any AWS key: **AWS Bedrock Agents**,
**AWS Bedrock Flows**, **AWS OpenSearch** (SigV4 over the REST API, managed domains and serverless collections) and
**AWS Quick Suite** (QuickSight API family: dashboards, SPICE refresh, PDF snapshots to S3, embed URLs including the
Quick chat agent, Quick Flows metadata, Quick Automate jobs). `workflows/pieces/aws-common/aws.ts` holds the shared
connection: region, optional role ARN and external id (STS AssumeRole from the engine task role), access keys for local
development only. The engine forks piece execution with a filtered environment, so the engine task sets
`AP_SANDBOX_PROPAGATED_ENV_VARS` to forward the ECS credential variables; the task role policy in
`infra/modules/ecs-activepieces/main.tf` grants the Bedrock, OpenSearch and Quick actions (dev scope `*`, TD-37).

Governance: model calls inside Bedrock Agents, Bedrock Flows and Quick run on AWS models outside the LiteLLM proxy and
the Responsible AI pipeline and are billed by AWS. The Studio labels these pieces **AWS-native AI**; upstream pieces that
call a vendor API with their own key (OpenAI, Mistral, …) are labelled **direct provider** and are not in the default
catalogue. Running a Quick Flow from outside Quick is not exposed by the public SDK (TD-35); Quick Automate jobs are.

### 5.7 MCP server: apps as tools for external agents

`backend/app/mcp_server.py` publishes selected apps as MCP tools at `POST /mcp` (streamable HTTP, JSON responses).
One tool per app marked published; a call runs the published flow through the gateway with the app's budget and
metering, a fresh session per call unless the client carries one. Credentials: tenant-scoped MCP keys (shown once,
hashed, revocable), Cognito tokens; app tokens are rejected. Limits and connection recipes for Amazon Quick Suite,
Claude Code and LiteLLM are in [MCP_PUBLISHING.md](MCP_PUBLISHING.md).

## 6. Security and Responsible AI boundaries

- **Credentials never reach the browser.** The gateway talks to Activepieces with a service account; per-app
  credentials live in Activepieces connections (encrypted) and as hashes in our database.
- **App tokens are scoped identities.** A workflow app calling `/chat` is authenticated as `workflow-app:<id>` with
  the app's tenant and the `workflow-app` group only. It cannot reach admin routes.
- **Virtual keys carry the budget.** Each app's LiteLLM key has its own monthly budget and model scope; the proxy
  enforces HTTP 429 when exceeded. The platform key used by the universal AI piece has its own budget.
- **The Responsible AI pipeline is opt-in per step, by design.** Only the Responsible AI Gateway piece passes through
  Presidio, Guardrails, Ragas and TruLens. The LiteLLM piece and the universal AI piece are proxy-only; this is the
  requested behaviour and is visible in FinOps as `purpose = workflow`.
- **Chat UI exposure.** The Activepieces chat page is public to anyone who knows the flow id (upstream design). For
  an internet-facing deployment put it behind the gateway (the `POST /workflows/apps/{id}/chat` proxy with Cognito)
  or an authenticating reverse proxy, and keep `AP_FRONTEND_URL` internal.
- **Builder access in CE** requires an Activepieces login. Flows are created in the service account's project, so
  builders sign in as a platform admin. This is acceptable for a small admin group and is the first thing the
  enterprise licence removes (SSO, project roles).
- **Piece governance** (which pieces a project may use) is enterprise-only. In CE, any installed piece is available
  to a builder, including pieces that call external services directly. The catalogue is reviewed, not enforced.
- **Secrets policy** applies ([NO_SECRETS_IN_GIT.md](NO_SECRETS_IN_GIT.md)): the service password, the encryption key
  and the JWT secret are environment values, never files in the repository.

## 7. Multi-tenancy

CE provides one platform with one TEAM project limit, and project membership is enterprise-only. Tenancy in this
integration is therefore enforced by the gateway registry (`workflow_apps.tenant_id`) and by LiteLLM keys, not by
Activepieces projects. Consequences:

- The Workflow Apps screen shows a tenant only its own apps; the Activepieces builder shows every flow in the
  shared project to whoever can log in there.
- For tenant isolation tier T1 ([MULTI_TENANCY_DESIGN.md](MULTI_TENANCY_DESIGN.md)) this is sufficient when builders
  are platform operators. For T2 (dedicated proxy) a dedicated Activepieces instance per tenant is the matching
  pattern. For true shared multi-tenant building, the enterprise licence provides per-tenant projects with managed
  authentication.

## 8. Enterprise licence: what changes

| Capability | Community (now) | Enterprise |
|---|---|---|
| Builder sign-in | Activepieces account | SSO via managed authentication (external token signed by the gateway), no second login |
| Embedding | iframe with login | embed SDK, hidden navigation, custom styling |
| Tenancy | gateway registry only | one Activepieces project per tenant, provisioned by the gateway |
| Piece governance | review only | piece sets per project (`managePiecesEnabled`) |
| Automation of the control plane | service-account user JWT (7 days, refreshed) | API keys |
| Audit | gateway audit events | Activepieces audit log in addition |

The control plane is written so that only `activepieces_client.py` changes: token acquisition (API key), project
creation per tenant and the builder URL (embed route) are isolated behind its interface.

## 9. Decisions (ADR summary)

| ID | Decision | Rationale |
|---|---|---|
| ADR-17 | Run Activepieces 0.92.0 community edition as a separate service; never fork or modify the checkout | Licence clarity, upgradeability, requirement that `activepieces-main` stays read-only |
| ADR-18 | Build custom pieces in this repository and install them as archives | Only distribution path that works in CE without npm publishing; framework 0.40.0 is not on npm, so bundling from the checkout's sources is required |
| ADR-19 | The gateway owns the control plane and credentials; the browser only ever sees Cognito-protected gateway routes and iframes | Keeps secrets out of the client and keeps tenancy enforcement in one place |
| ADR-20 | Three explicit AI call paths (governed gateway piece, direct LiteLLM piece, universal AI via custom provider) | Matches the requirement: AI inference through the proxy, Responsible AI processing only where chosen |
| ADR-21 | Workflow spend is ingested from the proxy spend log into `llm_usage_events` rather than forcing all inference through the gateway | FinOps and AIOps stay complete without widening the Responsible AI pipeline to calls that must bypass it |
| ADR-22 | Enterprise licence is the upgrade path for SSO, tenancy and piece governance; the client interface isolates the change | Avoids a rewrite later |
| ADR-23 | The builder is ours (Workflow Studio in the portal) and the engine is an internal backend with no public URL | Review of the first delivery: one product, one theme, one login; CE cannot re-theme or SSO-embed the engine UI (plan §4a) |
| ADR-24 | The Studio drives the engine only through an allow-listed set of flow operations on the gateway; publish, status, budgets and deletion stay on the app routes | Keeps tenancy, budgets and credentials enforced in one place and keeps the engine's surface small |
| ADR-25 | Studio-generated expressions use the engine 0.92 format `{{step['output']…}}` | Flows imported with an older schema are migrated by the engine; flows edited through the API are not, and the legacy form resolves to empty values (found in verification) |
| ADR-26 | AWS access from workflows uses the engine task role (optionally assuming per-tenant roles with an external id), never stored keys | No credential at rest in the engine; IAM is the control point; upstream AWS pieces (key-based) stay out of the default catalogue |
| ADR-27 | AI inside Bedrock or Quick is allowed but labelled as outside the proxy; the Studio shows governance badges on every AI piece | Builders see which steps are governed, proxy-metered, AWS-native or direct-provider before they use them |
| ADR-28 | Apps are published to external agents through one gateway MCP endpoint with tenant-scoped keys; calls run the app's published flow with its own budget | Keeps the engine internal, one audit trail, no per-app credentials leave the gateway |

## 10. Verification (2026-10-03, local stack)

Environment: `docker compose up -d` (LiteLLM main-stable backed by Groq, Activepieces 0.92.0, Jaeger), gateway running
natively on :8000 in proxy mode, `backend/.env` carrying the LiteLLM key and the Activepieces service password.

| Check | Result |
|---|---|
| Custom pieces bundled from the read-only checkout (`workflows/pieces/build.mjs`) | 2 archives, 363 KB and 364 KB, loadable in Node, `Piece` export found |
| Archives installed through `POST /api/v1/pieces` and metadata extracted by the worker | both at 0.1.1, actions `chat` / `list_models` and `chat_completion` / `list_models` visible in the catalogue |
| Service account | first sign-up became platform `ADMIN`; sign-in token reused by the gateway |
| AI provider "LiteLLM Proxy (Responsible AI)" | created as `custom` with `baseUrl` on the proxy and `Authorization` header; on `force` the credential is rotated to a scoped virtual key (alias `workflow-apps-platform-*`), never the master key |
| Backend unit tests (`backend/tests`) | 48 passed, including 15 new tests for tokens, templates, lifecycle, rollback, tenant isolation, usage sync and bootstrap |
| Frontend build | `vite build` succeeds; the Workflow Apps screen is in the bundle |
| End-to-end (`tests/workflow_apps_e2e.py --cleanup`) | 23 steps passed |

End-to-end steps, as run: status and bootstrap; create a `responsible-ai-chat` app; publish; chat through
`POST /workflows/apps/{id}/chat` answered `WORKFLOW-OK` with the gateway footer (model, tokens, Responsible AI mode,
request id) in 0.5 s; run `SUCCEEDED`; the call metered in `llm_usage_events` under `client_id = workflow-app:<id>`;
create a `litellm-chat` app; publish; chat answered `DIRECT-OK` via the proxy in 0.4 s with no Responsible AI
processing; usage sync pulled the proxy spend rows for the app keys (2 rows inserted, 0 on repeat); FinOps
`by_client` shows every app with its cost and tokens; an invalid app token is rejected with 401; both apps deleted
with their flows, connections and keys.

AWS dev (same day): modules `ecs-activepieces` and `api-gateway-workflows` applied from saved plans, gateway image rolled
with the engine settings (final image `1c6425c`), frontend republished. The startup bootstrap created the service account on the fresh
engine, installed both archives and the AI provider with no errors. The end-to-end script against the public API with a
Cognito ID token passed every functional step: both templates answered through the gateway (0.8 s and 0.6 s), run
`SUCCEEDED`, gateway metering and proxy spend visible in FinOps, invalid app token rejected. The only failures were in the
forced re-bootstrap, where a second gateway worker could not see the provider created at startup and tried to create a
duplicate; fixed by a database lease so one worker bootstraps at a time, duplicate removal by name and a retry after
deduplicating. The final AWS run passed all 23 steps.

Two demonstration apps created by the first run were left in place for inspection: "E2E Responsible AI chat" and
"E2E direct LiteLLM chat" (Workflow Apps tab, or `GET /workflows/apps`).

Defects found and fixed during verification: the worker fetches piece bundles from `AP_FRONTEND_URL`, so the API
must listen on the published port inside the container (`AP_PORT=8080`); a custom-auth `validate` receives the props
object directly (not `auth.props`); `/ai-providers?projectId` lists provider types, the configured providers with
display names come from `/ai-providers/configs`; the engine finalises a run shortly after the synchronous reply;
LiteLLM writes its spend log in batches, so ingestion is eventually consistent.

### 10a. Workflow Studio verification (2026-10-03, local stack and AWS dev)

| Check | Result |
|---|---|
| Backend unit tests | 65 passed, 12 of them for the Studio API (catalogue, flattening of router and loop trees, operation allow-list, tenant isolation, dynamic options, versions, connections including the OAuth2 URL, step test, run detail and retry) |
| Frontend build | `vite build` succeeds; Studio, step picker, connection dialog, runs panel and app chat are in the bundle |
| `tests/workflow_studio_e2e.py`, local stack | 23 of 23 steps |
| `tests/workflow_studio_e2e.py`, AWS dev (gateway image `0aa6c16`, task definition `:10`) | 23 of 23 steps |
| `tests/workflow_apps_e2e.py --cleanup`, AWS dev | 23 of 23 steps (templates, publish, chat, metering, spend sync, token boundary) |

Studio steps, as run: curated catalogue (19 pieces) and piece metadata; blank app; trigger sample saved; gateway chat step
added with the app's own connection; **step test** executed by the engine against the sample (answer `STUDIO-OK`, 1.0 s
local, 1.2 s AWS); reply step added; flow renamed; draft valid; publish; chat through the gateway answered with the Studio
footer (0.4 s, 0.5 s); run `SUCCEEDED` with per-step input and output in the run detail; versions listed (`LOCKED`); router
added, Code step inside its first branch, loop added, all three removed again; `LOCK_AND_PUBLISH` rejected as a Studio
operation (400); app deleted.

Defects found and fixed: a step added through the API with `{{trigger['message']}}` resolved to an empty string at run time
(the chat step then failed with a 422 from the gateway). Engine 0.92 stores references as `{{step['output']['field']}}`
and migrates only imported flows; the Studio now emits that format (ADR-25). `POST /v1/sample-data/test-step` returns the
queued TESTING run rather than the result (the engine streams it to its own UI over a websocket); the Studio polls the run
until it settles.

Rollout observation in AWS: for about a minute both task revisions served traffic and a run of the Studio suite in that
window saw 404s from the old revision; the rerun after the old task drained passed every step.

### 10b. AWS pieces and MCP publishing verification (2026-10-05)

| Check | Result |
|---|---|
| Backend unit tests | 78 passed, 13 of them for the MCP server (keys, tool publishing, tenant isolation, JSON-RPC methods, fresh sessions, app-token rejection, body and batch caps) |
| Pieces | six archives build and typecheck (`workflows/pieces`), 0.2–0.4 MB each; all six install on the local engine at bootstrap |
| `tests/mcp_e2e.py`, local stack | 19 of 19: app published as tool `e2e_chat`, key issued, `initialize` (2025-06-18), `tools/list`, `tools/call` answered `MCP-OK` with the gateway footer through the Responsible AI pipeline, fresh session per call and client session honoured, unknown tool as `isError`, OAuth resource metadata, bad key 401 with `WWW-Authenticate`, disabled app hidden, revoked key 401, tool row removed with the app |
| `tests/workflow_studio_e2e.py`, local stack (regression) | 23 of 23 |
| Local engine | all four AWS pieces `installed` by the bootstrap; metadata lists 4 + 2 + 6 + 10 actions with `CUSTOM_AUTH` connections |

| AWS dev engine (task definition `:2`, task role policy + `AP_SANDBOX_PROPAGATED_ENV_VARS`) | the gateway bootstrap on image `13b9294` installed all four AWS pieces (`installed`, no errors) |
| `tests/mcp_e2e.py`, AWS dev over the public API (gateway image `13b9294`, task definition `:11`, `PUBLIC_BASE_URL` set) | 19 of 19; `tools/call` answered through the Responsible AI pipeline with the gateway footer |
| `tests/aws_pieces_smoke.py`, AWS dev | 18 of 18: one connection per piece created with the region only and **validated with the task role** (STS from inside piece execution, which proves the credential propagation); Bedrock `list_agents` → `{"agents": [], "knowledgeBases": []}` and `list_flows` → `{"flows": []}`; OpenSearch `raw_request` to a bogus host was signed and sent (`getaddrinfo ENOTFOUND`); Quick `list_dashboards` in us-east-1 reached the service: `UnsupportedUserEditionException: Account … is not subscribed for QuickSight` |

Not verified (no resources in dev): `invoke_agent`, `retrieve`, `retrieve_and_generate`, `invoke_flow`, OpenSearch
reads and writes against a real domain, Quick snapshot export, embed URL, Quick Automate jobs. They use the same
connection and SDK paths as the verified calls; first use against real resources should be treated as a test.

## 11. Open items and follow-ups

- Builder login and separate engine URL raised at review: resolved by the Workflow Studio (Track 2 of
  [WORKFLOW_STUDIO_PLAN.md](WORKFLOW_STUDIO_PLAN.md), Sprints WS-1 to WS-3 in [ROADMAP.md](ROADMAP.md)).
- Enterprise licence evaluation for per-tenant engine projects and piece governance (section 8; TD-31, now Low).
- Production shape of the engine: own database, Redis queue, APP/WORKER split (TD-32).
- Add the workflow spend sync to the AIOps dependency checks and alarms.
- Studio polish candidates: drag-and-drop step reordering (MOVE_ACTION is already allow-listed), markdown preview for
  replies, OIDC connections, per-step run timeline while a test is running (engine streams it over a websocket that the
  Studio does not consume).
- Activate brand values for `theme.css` once the brand source is supplied.
- Inbound webhook and form triggers need a gateway route now that the engine has no public URL (TD-34). The Studio
  renders piece help texts as markdown and replaces the engine's chat, form and webhook URL notes with its own.
