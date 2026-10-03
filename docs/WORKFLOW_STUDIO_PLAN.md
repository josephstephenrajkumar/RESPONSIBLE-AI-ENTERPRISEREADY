# Workflow Studio: integrating the workflow builder 100% into our codebase

| | |
|---|---|
| Status | Plan for decision, 2026-10-03. No code changed |
| Trigger | Review feedback on the first deployment: the builder opens on a separate URL and shows an Activepieces sign-up/sign-in; the expectation was an SDK-style integration inside our front end |
| Related | [ACTIVEPIECES_INTEGRATION.md](ACTIVEPIECES_INTEGRATION.md) (what was built), TD-30, TD-31 |

## 1. Why it looks the way it does today

Activepieces is a server (API, worker, Postgres) with its own single-page web application. The community edition has no
single sign-on and no way to serve its UI from another application, so the only way to show its builder inside our React
app was an iframe pointing at the engine's own origin. Inside that iframe the engine asks for its own login, because it
does not know who our Cognito user is. The "SDK" Activepieces sells is exactly this iframe plus a signed token that logs
the user in silently and hides the engine's navigation; that SDK and the token exchange behind it are enterprise-licensed
(`packages/ee/embed-sdk`, `managed-authn`, gated by `embeddingEnabled`, which is `false` in the community plan).

Two things are therefore true at once:

- the engine will always be a separate backend service, like the LiteLLM proxy is. An SDK cannot run a workflow engine
  in the browser;
- the builder *user interface* does not have to be the engine's. It can be ours, or it can be the engine's shown without
  a login and without a visible URL.

## 2. Verified mechanics (read in the 0.92.0 source)

| Mechanism | Finding | Why it matters |
|---|---|---|
| Engine session token | HS256 JWT signed with `AP_JWT_SECRET`, key id `1`, issuer `activepieces`, payload = the principal `{id, type: USER, projectId, platform: {id}}`, 7-day expiry (`access-token-manager.ts`, `jwt-utils.ts`) | We hold that secret in Secrets Manager. The gateway can mint a valid engine session without the enterprise token exchange |
| Web session | The UI is "logged in" when `localStorage` has `token` (and `projectId`); user id is decoded from the token (`authentication-session.ts`) | A same-origin page can establish the session; no sign-in screen is shown |
| Web API base | `window.location.origin` + `/api` (`api.ts`) | The UI must be served from the engine's origin; it cannot be mounted under a path of our app |
| Public chat | `/chats/{flowId}` and `/api/v1/webhooks/{flowId}/sync` are public routes | Our own chat UI over the gateway proxy removes the need for them |
| Embed page | `/embed` exists in the community UI but only works with the enterprise SDK's message protocol | Re-implementing that protocol copies enterprise-licensed design; not proposed |
| Everything the builder does | is a REST call: pieces catalogue and property options, flows and operations, connections, runs, step tests | A builder written in our React app can drive the engine through the gateway |

## 3. Options

| | A. Enterprise embed SDK | B. Community "seamless session" | C. Fork the engine UI into our repo | D. Our own Workflow Studio on the engine API | E. Hybrid D + B |
|---|---|---|---|---|---|
| Separate URL visible | No (iframe, custom domain possible) | Only as iframe source; user never navigates there | No | No engine URL at all; engine fully internal | No |
| Engine login shown | No (token exchange) | No (gateway-minted session) | No (our auth) | No | No |
| Share of UI in our codebase | Thin wrapper | Thin wrapper + session route | 100 %, but a copy of ~1,000 files we must keep merging | 100 %, our components | Mostly ours |
| Multi-tenant builder access | Per-tenant projects, roles | One platform; builders act as the service identity or as platform admins | Same as B unless licensed | Enforced by our registry; engine is a backend | As D |
| Piece governance | Piece sets | None (catalogue is open) | None | We choose which pieces the Studio offers | As D |
| Licence | Enterprise (pricing on request) | MIT | MIT core; `ee` folders excluded | MIT | MIT |
| Effort | 1–2 weeks after licence | ~1 week | 4–6 weeks, then permanent merge cost | 5–6 weeks for v1, 10+ for parity | 6–7 weeks |
| Upgrade risk | Low | Medium: relies on token claims and storage keys; re-test per engine release | High | Low: REST API is the stable surface | Medium |
| What you lose | Nothing | Engine chrome stays visible inside the iframe | Nothing, at a high maintenance cost | Visual canvas, loops/routers, OAuth-based pieces until built | Little |

Option C is listed for completeness and not recommended: the engine UI is a bun/turbo monorepo package with its own
routing, state, sockets and i18n; a fork diverges within weeks and the review already rejected it.

## 4. Recommendation

Deliver in two tracks, with the enterprise licence kept as the optional third.

### Track 1 (about one week): remove the login and the visible URL on the community edition

1. **Gateway-minted engine session.** New gateway route `GET /workflows/session/{appId}` (Cognito, `manage_workflows`)
   returns a one-time code. The engine's HTTP API gets one extra route, `ANY /_session/{proxy+}`, forwarded to the
   gateway, so a page on the *engine origin* can set the session. That page exchanges the code, writes `token` and
   `projectId` to the engine's `localStorage`, and redirects to `/flows/{flowId}`. The token is signed by the gateway with
   `AP_JWT_SECRET` for the service identity (today) or for a per-user engine account (step 3). Result: the iframe opens the
   builder with no sign-in, no sign-up.
2. **Our own chat UI.** Replace the embedded engine chat page with our existing chat window talking to
   `POST /workflows/apps/{id}/chat`. Block `/chats/*`, `/forms/*` and the public webhook paths at the engine's HTTP API
   (route them to the gateway, which answers 404). This closes TD-30 and makes the chat 100 % ours.
3. **Per-user engine identity (optional in this track).** Provision one engine user per gateway admin on first use
   (sign-up API with a random password that is discarded, platform role `ADMIN` so the shared project is visible), and
   mint sessions for that user. Gives per-person attribution in the engine; otherwise the service identity is used and our
   registry remains the audit source.
4. **Single domain (cosmetic).** A `workflows.` subdomain in front of the engine API needs Route 53 and ACM, which the
   repository does not have yet. Not required for the user journey, since the engine origin only ever appears as an iframe
   source.

Known limits of Track 1: the engine's own header and side navigation stay visible inside the iframe, and a platform-admin
identity can reach engine settings pages from there. Both are why Track 2 exists.

### Track 2 (five to six weeks): Workflow Studio, 100 % in our codebase

A builder written in our React app, driving the engine only through the gateway. The engine becomes an internal backend
service exactly like the proxy: no public URL, no engine UI, no engine login. The second HTTP API is deleted.

| Studio feature | Engine API it uses (via gateway) | Notes |
|---|---|---|
| Piece catalogue and search | `GET /v1/pieces`, `GET /v1/pieces/{name}` | We curate which pieces are offered (governance without the enterprise feature) |
| Step editor with property forms | piece metadata `props` (short/long text, number, checkbox, static dropdown, JSON, object, array); dynamic dropdowns through `POST /v1/pieces/options` | Form renderer generated from metadata, same approach as the Proxy Manager's settings catalogue |
| Flow structure | `POST /v1/flows/{id}` operations: `UPDATE_TRIGGER`, `ADD_ACTION`, `UPDATE_ACTION`, `DELETE_ACTION`, `MOVE_ACTION` | v1: trigger plus a linear list of steps; v2: router branches and loops |
| Data mapping between steps | expressions `{{step_1['answer']}}` built with a picker from previous steps' sample data | sample data via `SAVE_SAMPLE_DATA` and step test results |
| Test a step / test the flow | `POST /v1/step-run`, `POST /v1/webhooks/{id}/test`, `GET /v1/flow-runs/{id}` | Run view with per-step input/output |
| Connections | `POST /v1/app-connections` for custom-auth and secret-text pieces (ours, HTTP, most SaaS keys) | OAuth2 pieces need the engine's OAuth callback; deferred to v2 or routed through the gateway |
| Publish, versions, enable/disable | `LOCK_AND_PUBLISH`, `CHANGE_STATUS`, `USE_AS_DRAFT`, `GET /v1/flows/{id}/versions` | Already partly implemented in the control plane |
| Runs and logs | `GET /v1/flow-runs`, `GET /v1/flow-runs/{id}` | Already partly implemented |

Scope for v1: linear flows; our two pieces plus the universal AI, HTTP, Code, Data Mapper, Delay, Schedule and Webhook
pieces; custom-auth and secret connections; test, publish, runs; templates as today. What v1 does not have: the free-form
canvas, loops and routers, and OAuth-based SaaS pieces. For those, Track 1 remains available as an "advanced editor" link
(hybrid E) until v2 covers them.

### Track 3 (optional): enterprise licence

Buys per-tenant projects and roles, piece sets, audit log and the official embed SDK. Worth it when tenants' own staff
must build flows side by side, or when the full canvas must be embedded for them. The control-plane client already
isolates token acquisition, project creation and builder URL, so adopting it later touches one module.

## 4a. Theming as the Activate portal: the deciding factor between tracks 1 and 2

Requirement raised at review: the whole product must look and behave as the Activate portal.

| | Track 1 (engine UI, seamless session) | Track 2 (Workflow Studio, our components) |
|---|---|---|
| Can the builder take the Activate theme? | No. `customAppearanceEnabled` is `false` in the community plan; the engine UI keeps its own logo, colours, fonts and layout inside the iframe. With the enterprise licence only name, logo and primary colour change; the layout stays Activepieces' | Yes, completely. The Studio is built from our components and inherits the portal theme like every other screen |
| Experience boundary | Visible seam: portal chrome around a differently styled application | None |
| Navigation and permissions | The engine's own header, side navigation and settings pages remain reachable inside the iframe | Only what we build is reachable; piece catalogue curated by us |
| Time to first usable builder | ~1 week | ~6 weeks (theme foundation 1–2 weeks in parallel, Studio v1 5–6 weeks) |
| Longevity | Stop-gap; most of it is discarded when the Studio ships | Target state |
| Risk | Depends on engine internals (token claims, storage keys) | Depends on the engine's REST API, its stable surface |

Reading: if the Activate theme is a requirement, track 1 cannot meet it and is only worth doing as a short stop-gap for
builders who need the engine canvas before the Studio exists. Recommended sequence:

1. **Theme foundation (1–2 weeks, in parallel).** Design tokens (colour, type, spacing, radius, elevation) from the
   Activate brand guide or Figma library, a small shared component set (buttons, inputs, tables, panels, dialogs, notices,
   tabs), and the existing screens (Chat, Responsible AI, Proxy Manager, FinOps, AIOps, Configuration) moved onto them.
   Today the front end is one global stylesheet with ad-hoc classes, so this is needed for "the entire software" regardless
   of the builder.
2. **Workflow Studio v1 on those components (5–6 weeks).** No engine UI, no engine URL, no engine login.
3. **Track 1 only if a builder is needed in the next weeks**; budget it as disposable (5 MD).

## 5. Decisions needed

1. Confirm the Activate theme as a requirement for the whole product (this makes track 2 the target).
2. Provide the Activate brand source (brand guide or Figma library) for the theme foundation.
3. Decide whether track 1 is wanted as a disposable stop-gap while the Studio is built.
4. Whether to request enterprise pricing in parallel for the multi-tenant builder case.

## 6. Effort summary

| Track | Design | Development | Testing | Total (MD) |
|---|---|---|---|---|
| 1. Seamless session, own chat UI, blocked public routes | 1 | 3 | 1 | 5 |
| 1 + per-user engine identities | +0.5 | +1.5 | +0.5 | 7.5 |
| 2. Workflow Studio v1 (linear flows, curated pieces, connections, test, publish, runs) | 4 | 18 | 6 | 28 |
| 2 v2 (branches, loops, OAuth pieces, data picker polish) | 3 | 14 | 5 | 22 |
