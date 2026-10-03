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
| **C. Separate service + control plane in the gateway + iframe (chosen)** | Activepieces runs beside the gateway. The gateway signs in with a service account, installs our pieces, configures the AI provider, creates and publishes flows from templates, issues per-app credentials and ingests spend. The front end iframes the chat UI and the builder from an allow-listed origin | Works in CE with no forked code; everything we add lives in this repository; the upgrade to B is additive |
| D. Link-out only | Buttons that open Activepieces in a new tab | Fallback inside C for browsers that block third-party storage in iframes |

## 4. Target architecture

```text
Browser (React, :5173)                                    Activepieces (:8080, CE 0.92.0)
  Chat | Responsible AI | Proxy Manager | FinOps | AIOps     API + worker + UI, PGlite/Postgres
  Workflow Apps ───────── iframe /chats/{flowId} ──────────► public chat UI
                 ───────── iframe /flows/{flowId} ──────────► builder (AP login in CE)
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

### 5.3 Front end (`frontend/src/components/WorkflowApps.jsx`)

A new **Workflow Apps** tab (permission `manage_workflows`) with:

- engine status (reachable, bootstrap state, piece versions, AI provider) and a bootstrap button,
- the app table (name, template, status, budget, created) with Open builder, Open chat, Publish, Disable/Enable,
  Runs and Delete,
- a create form (name, template, Responsible AI mode, model from `/gateway/models`, monthly budget),
- an embedded builder (iframe to `{public}/flows/{flowId}`, with "open in new tab" fallback),
- an embedded chat (iframe to `{public}/chats/{flowId}`) and a small "test through the gateway" composer that uses
  `POST /workflows/apps/{id}/chat`, so the round trip can be exercised without leaving the gateway's auth boundary.

The existing Chat tab is unchanged. The chat app re-implemented on Activepieces is the `responsible-ai-chat` template,
visible as "Open chat" on any app created from it.

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

Local: `docker compose up -d` now also starts `activepieces` (image 0.92.0, PGlite, in-memory queue, port 8080,
`AP_ALLOWED_EMBED_ORIGINS` for the Vite dev origins, `host.docker.internal` for the natively running gateway).
Secrets (`AP_ENCRYPTION_KEY`, `AP_JWT_SECRET`, `ACTIVEPIECES_SERVICE_PASSWORD`) have dev-only defaults or live in the
gitignored `backend/.env`.

AWS dev (not deployed yet; waits for the deploy instruction): an `ecs-activepieces` Terragrunt module with the
`APP` and `WORKER` container types, Postgres (a second Aurora database or the existing cluster), ElastiCache Redis,
an internal ALB target behind the API Gateway or CloudFront behaviour `/workflows/*`, `AP_FRONTEND_URL` set to the
public URL, `AP_ALLOWED_EMBED_ORIGINS` set to the CloudFront domain, `AP_PIECES_SYNC_MODE=NONE` with archives
installed by the gateway, and all secrets in Secrets Manager. The gateway task gets `ACTIVEPIECES_API_URL` on the
VPC-internal address.

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

AWS dev (same day): modules `ecs-activepieces` and `api-gateway-workflows` applied from saved plans, gateway image `f1b0192`
rolled with the engine settings, frontend republished. The startup bootstrap created the service account on the fresh
engine, installed both archives and the AI provider with no errors. The end-to-end script against the public API with a
Cognito ID token passed every functional step: both templates answered through the gateway (0.8 s and 0.6 s), run
`SUCCEEDED`, gateway metering and proxy spend visible in FinOps, invalid app token rejected. The only failures were in the
forced re-bootstrap, where a second gateway worker could not see the provider created at startup and tried to create a
duplicate; fixed by falling back to the recorded provider id and adopting an existing provider on a duplicate-name 409.

Two demonstration apps created by the first run were left in place for inspection: "E2E Responsible AI chat" and
"E2E direct LiteLLM chat" (Workflow Apps tab, or `GET /workflows/apps`).

Defects found and fixed during verification: the worker fetches piece bundles from `AP_FRONTEND_URL`, so the API
must listen on the published port inside the container (`AP_PORT=8080`); a custom-auth `validate` receives the props
object directly (not `auth.props`); `/ai-providers?projectId` lists provider types, the configured providers with
display names come from `/ai-providers/configs`; the engine finalises a run shortly after the synchronous reply;
LiteLLM writes its spend log in batches, so ingestion is eventually consistent.

## 11. Open items and follow-ups

- Enterprise licence evaluation for SSO embedding and per-tenant projects (section 8; TD-31).
- `ecs-activepieces` Terraform module, Aurora database, Redis and secrets for AWS dev; deploy on instruction (TD-32).
- Place the public chat page behind the gateway or an authenticating proxy before any internet exposure (TD-30).
- Add the workflow spend sync to the AIOps dependency checks and alarms.
- Piece catalogue review: decide which community pieces are acceptable for builders and document the list.
