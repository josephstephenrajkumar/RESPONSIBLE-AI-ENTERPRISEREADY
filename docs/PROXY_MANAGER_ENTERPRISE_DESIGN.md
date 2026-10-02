# Proxy Manager — Enterprise Design: settings hierarchy, control-plane integration, guided configuration

**Status**: proposed, 2026-10-02 · **Owner**: platform architecture · **Feeds**: [ROADMAP.md](ROADMAP.md) (Sprints 3–5, M13–M15),
[ARCHITECTURE_DESIGN.md](ARCHITECTURE_DESIGN.md) (ADR-14…16), [MULTI_TENANCY_DESIGN.md](MULTI_TENANCY_DESIGN.md).

This document answers four questions raised after the Proxy Manager became fully editable (Routing & Settings screen):

| # | Question | Today | Target | Sprint |
|---|---|---|---|---|
| 1 | Settings are for one (default) tenant. How do I set them per tenant, then per app or department? | Flat `gateway_settings`; LiteLLM router/litellm/cache/general settings are proxy-global; teams and keys exist but are not linked to settings | Scoped settings: Platform → Tenant → Department → Application → Request, mapped onto LiteLLM organization → team → virtual key → per-request overrides, narrow-only inheritance, scope switcher in the UI | 3 (phase 1), 4 |
| 2 | Even with one tenant, I want settings by app or department. | Same as above | Same model with a single tenant `default`: departments = teams, apps = keys | 3 |
| 3 | Two control planes (AI App, AI Gateway). How does the App platform discover and embed the Proxy Manager, with the gateway granting authentication, so nothing is served to a tenant without a gateway grant? | Cognito users and roles; internal-only proxy; allow-listed passthrough; no tenant/app registry, no machine credentials, no discovery document | Gateway publishes `/.well-known/ai-gateway` + a capability manifest; OAuth2 clients and token exchange issued by the gateway; tenant/app registry gates every call at network, token and key layers; webhooks for events | 4 |
| 4 | There is a lot of configuration. How do I know what is right? Examples, best practices and AI-assisted guidance should be built in. | LiteLLM field descriptions, inline placeholders, shipped defaults | Settings catalogue with recommendations per environment, profiles (presets) with diff preview, server-side validation, and a propose-only configuration copilot grounded in docs, current config and FinOps/AIOps signals | 3 (catalogue, validation, profiles), 5 (copilot) |

Facts verified against the installed LiteLLM (`/openapi.json`, 2026-10-02): `/organization/new` (budgets, models, RPM/TPM per org);
`/team/new` accepts `router_settings`, `guardrails`, `policies`, `model_aliases`, `tags`, `secret_manager_settings`, `organization_id`;
`/key/generate` accepts `router_settings`, `guardrails`, `tags`, `allowed_routes`, `enforced_params`, `auto_rotate` + `rotation_interval`;
`/team/{team_id}/callback` (per-team logging callbacks) is not licence-gated; `/budget/new` creates reusable budgets for orgs, teams, keys and
end users; `/customer/*` manages end-user budgets; `/jwt/key/mapping/*` maps JWT claims to keys. Key regenerate and some UI fields
(`premium_field`) remain Enterprise-only; where that matters the gateway implements the feature itself (as done for key rotation).

---

## 1. Settings hierarchy (questions 1 and 2)

### 1.1 Scopes and their LiteLLM counterparts

```text
Platform (proxy-global)            → LiteLLM router_settings / litellm_settings / general_settings / cache   (Routing & Settings today)
 └─ Tenant                          → LiteLLM Organization (budget, allowed models, RPM/TPM)                 + gateway tenant record
     └─ Department (optional)       → LiteLLM Team (budget, models, aliases, limits, guardrails, policies, tags, team router_settings, team callbacks, secret_manager_settings)
         └─ Application / agent     → LiteLLM Virtual key (budget, limits, models, guardrails, tags, key router_settings, allowed_routes, enforced_params, auto-rotation)
             └─ Request             → per-call overrides injected by the gateway (fallbacks, num_retries, timeout, metadata.tags, cache controls)
```

A single-tenant deployment is the same tree with one tenant named `default`: departments are teams and applications are keys.
Question 2 is therefore solved by the same design as question 1.

### 1.2 Which setting is defined where

Legend: **D** defines · **N** may narrow (subset / stricter / smaller) · **I** inherits only · **L** locked at platform

| Setting | Platform | Tenant | Department | Application | Request |
|---|---|---|---|---|---|
| Master key, database, store-in-DB, bootstrap callbacks (OTel) | L | — | — | — | — |
| Provider enablement, provider credentials, credential store | D | N (own store, own keys in T2) | I | I | — |
| Model catalogue, prices, model groups | D | N (allowed models) | N (models, aliases) | N (models) | — |
| Default chat model, judge model | D | N | N | N | model param within allowlist |
| Budgets, soft budgets, RPM/TPM/TPD, parallel requests | D (platform guard-rails) | D (org) | N (team ≤ org) | N (key ≤ team) | — |
| Retries, timeout, cooldown, routing strategy | D | I | N (team `router_settings`) | N (key `router_settings`) | `num_retries`, `timeout` |
| Fallbacks | D | I | N | N | `fallbacks` |
| Guardrails (proxy-side) | D (global, default-on) | N (add) | N (add; `disable_global_guardrails` only if delegated) | N | — |
| Observability callbacks | D | N (team callbacks with own Langfuse keys) | N | I | — |
| Cache backend (Redis) | L | — | — | — | — |
| Cache behaviour (TTL, no-cache, namespace) | D | N (namespace) | N | N (`allowed_cache_controls`) | `cache` controls |
| MCP servers and access groups | D | N (access groups) | N | N | — |
| Tags (cost allocation, tag routing) | D (taxonomy) | D | D | D | `metadata.tags` |

Rule: a lower scope may only **narrow** its parent unless the parent marks the setting *delegable*. The effective value shown in the
UI always carries its source scope and whether it is locked.

### 1.3 Gateway data model and request path

- `gateway_settings` gains `scope_type` (`platform|tenant|department|app`), `scope_id`, `locked`, `delegable`. Resolution:
  app → department → tenant → platform → environment default. `effective_view(scope)` returns `{value, source_scope, locked}` per key.
- New registry tables: `tenants` (id, name, status, isolation tier, `litellm_organization_id`, credential store, proxy URL for T2),
  `departments` (tenant, `litellm_team_id`), `applications` (tenant, department, `client_id`, environment `buildtime|runtime`, status,
  hashed `litellm_key`). Everything already tagged with `tenant_id` (usage, audit, violations) joins to these.
- Request path: the gateway resolves the caller → tenant/department/app → calls the proxy with the **application's virtual key**
  (so LiteLLM enforces budgets, limits, model scope, guardrails per app) and injects request-level overrides from the effective
  settings (`fallbacks`, `num_retries`, `timeout`, `metadata.tags`, cache controls). This replaces today's single gateway key.
- Writes from the Proxy Manager at tenant/department/app scope map to `/organization/update`, `/team/update`, `/key/update`;
  gateway-owned settings (default/judge model, enablement, allowlist) are written to `gateway_settings` with the scope.

### 1.4 UI

Scope switcher as a breadcrumb at the top of the Proxy Manager (Platform › Tenant › Department › Application). Every field shows
the effective value, an "inherited from …" chip, a lock icon, and *Override here* / *Revert to inherited* actions; saving shows a
diff. Roles: `admin`/`model-admin` at platform scope, `tenant-admin` for one tenant, `department-admin` for one team; the API enforces
the same scoping. Sections that are platform-only (cache backend, general settings, bootstrap file) are hidden at lower scopes.

---

## 2. Two control planes (question 3)

### 2.1 Responsibilities

| Plane | Owns | Needs from the other |
|---|---|---|
| **AI Gateway control plane** (this gateway + LiteLLM) | identity of model consumers, entitlements, model catalogue, budgets, policies/guardrails, metering, Proxy Manager API and UI | nothing at run time; tenant and app lifecycle events are optional inputs |
| **AI App control plane** (where applications are built, deployed and operated) | application lifecycle, environments, developer teams, deployment pipelines | discover what the gateway offers, obtain credentials for apps at build and run time, embed or link tenant-scoped management, receive events |

### 2.2 Runtime discovery contract

- `GET /.well-known/ai-gateway` (unauthenticated, cacheable): gateway version, OIDC issuer and JWKS, token and token-exchange
  endpoints, scopes, data-plane base URL (OpenAI-compatible `/v1/*` plus `/chat`), management base URL (`/gateway/admin/*`),
  capability manifest URL, UI embed URL, OpenAPI URL, webhook event catalogue.
- `GET /gateway/capabilities` (authenticated): the sections and actions available to **this principal and scope**, each with
  routes, required scopes and a JSON Schema for its form. Schemas are derived from LiteLLM's own metadata
  (`/config/list`, `/cache/settings`, `/public/providers/fields`, `/openapi.json`) and the gateway's settings catalogue, so a new
  LiteLLM capability appears in the manifest without an App-platform release (see "Capability discovery" in
  [LITELLM_PROXY_MANAGER.md](LITELLM_PROXY_MANAGER.md)). Versioned with `capabilities_version` and an ETag.
- Embedding options for the App control plane: (a) render natively from the schemas (recommended, consistent UX), (b) micro-frontend
  or iframe of the Proxy Manager with token exchange and scope context passed by `postMessage`, (c) deep links into the gateway UI.
- Events (webhook or EventBridge): `tenant.provisioned`, `app.registered`, `app.credential.issued|rotated|revoked`,
  `budget.threshold`, `model.added|deprecated`, `capabilities.changed`. The App platform reacts (for example surfaces a new model to
  developers) without polling.
- SDKs generated from the gateway's `/openapi.json`.

### 2.3 Authentication and entitlement — the gateway is the authority

Principals: humans (Cognito or federated IdP, roles), the App control plane itself (service), tenant applications at build time
(CI, SDKs, evaluation pipelines) and run time, and third-party applications.

1. **Tenant onboarding is the grant.** A tenant exists only when the gateway creates the tenant record and the LiteLLM organization.
   Nothing is served before that.
2. **Application registration** under a tenant creates an OAuth2 client (Cognito app client, `client_credentials`, resource-server
   scopes `gateway.inference`, `gateway.manage:tenant`, `gateway.manage:app`, `gateway.read:spend`) and a LiteLLM virtual key created
   server-side and never disclosed; the gateway maps `client_id` → tenant/department/app/key. Build-time and run-time are separate
   clients and keys with different scopes, budgets and `allowed_routes`; keys use `auto_rotate` with a `rotation_interval`.
3. **Token exchange** for the App control plane acting for a tenant administrator: it exchanges its user token for a gateway token
   carrying `tenant_id`, scopes and an `act` claim. Cognito does not implement RFC 8693, so the gateway exposes `/oauth2/exchange`,
   validates the inbound token against the App platform's JWKS and issues a short-lived gateway JWT signed with a KMS key
   (alternative: federate the App platform's IdP into Cognito).
4. **Validation on every call**: issuer, `aud=ai-gateway`, expiry, tenant status `active`, application status `active`, scope. Then
   the gateway swaps in the application's LiteLLM key.
5. **Three enforcement layers** make "no grant → not served" hold even if one layer is misconfigured: network (the proxy sits on an
   internal ALB reachable only from the gateway's security group — already true), token validation and the tenant/app registry, and
   LiteLLM key state (blocked, expired, budget). Revocation blocks the key and disables the client; propagation is seconds.
6. **Third-party applications** are registered as external apps under a tenant with their own client, narrow model scope, spend tags
   and optional mTLS or IP allow-list.
7. Every grant, exchange, rotation and revocation is written to `policy_audit_events` with `tenant_id` (surfaced by the planned admin
   audit view).

In the T2 dedicated-proxy tier a tenant may talk to its own proxy directly; LiteLLM's JWT auth (`/jwt/key/mapping`) and SSO settings
apply there. In the shared T1 tier the gateway remains the only client of the proxy.

### 2.4 Onboarding and call sequence

```text
App CP ──(service token)──► Gateway: POST /gateway/admin/tenants            → tenant + LiteLLM organization
App CP ──────────────────► Gateway: POST /gateway/admin/tenants/{t}/apps    → OAuth2 client (id + secret shown once), LiteLLM key (hidden)
App CP (build) ──client_credentials──► Cognito ──► token(scope=gateway.inference, tenant=t)
App ──(bearer token)──► Gateway /chat or /v1/chat/completions ─(app's LiteLLM key, injected overrides)─► LiteLLM ─► provider
Gateway ◄─ x-litellm-* headers ─ meter (tenant, department, app, purpose) ─ FinOps / AIOps
```

---

## 3. Guided configuration (question 4)

### 3.1 Settings catalogue

`docs/settings-catalog/*.yaml`, served as `GET /gateway/admin/settings-guide`. Per setting: plain-language description (LiteLLM's
`field_description` plus curated text), type and bounds, **recommended values per environment** (dev, staging, prod) and workload
(chat, batch, agents), rationale, risks, dependencies ("`cooldown_time` pairs with `allowed_fails`"), examples, and docs links for the
running LiteLLM version. UI: an info icon opens a side panel; a "Recommended" chip appears when the value matches the recommendation.

Starting recommendations (to be refined with data):

| Setting | Dev | Prod chat | Prod agents/batch | Why |
|---|---|---|---|---|
| `num_retries` | 1 | 2 | 3 | balance recovery against added latency |
| `timeout` (s) | 30 | 30 | 120 | below the ALB/API Gateway idle timeout; long for tool loops |
| `allowed_fails` / `cooldown_time` | 3 / 30 | 5 / 60 | 5 / 60 | avoid flapping deployments out of rotation |
| `routing_strategy` | simple-shuffle | latency-based-routing | usage-based-routing-v2 | latency for users, quota balance for throughput |
| fallbacks | one cheaper model per group | cross-provider pair per group | same | outage and 429 resilience |
| cache TTL (s) | 300 | 3600 | 0 (off) | cache only stable prompts |
| judge model | cheapest capable | `judge-fast` group | same | evaluation was ~50 % of spend |

### 3.2 Profiles (presets)

*Starter (dev)*, *Production — cost-optimised*, *Production — latency-optimised*, *Regulated (PII-strict guardrails on)*,
*Agentic / MCP*. Each is a bundle over router, LiteLLM, cache, guardrail and general settings stored like
`litellm_runtime_defaults.json`; applying one shows a diff and extends today's *Re-apply shipped defaults*.

### 3.3 Validation and preflight

`POST /gateway/admin/litellm-config/validate` runs before every save and returns warnings and errors: fallbacks reference existing,
enabled models and do not loop; router timeout ≤ gateway and ALB idle timeouts; `allowed_fails`/`cooldown_time` sanity; cache TTL
bounds; judge model enabled and not more expensive than the chat model; callback variables present; child budgets ≤ parent;
Enterprise-only fields flagged.

### 3.4 AI-assisted configuration copilot

An "Ask the gateway" panel in the Proxy Manager, grounded on: the settings catalogue, LiteLLM docs and OpenAPI for the running
version, the **effective configuration of the selected scope**, FinOps/AIOps signals (error rates and 429s per model, p95 latency,
retry and fallback counts, spend, cache hit rate) and recent audit history. It can explain a setting, recommend values for a stated
goal ("cut cost 30 % without raising p95"), diagnose ("why are requests slow since yesterday") and **propose a change as a reviewable
diff** that a human approves; it never applies anything itself, is bound to the user's RBAC scope, runs through the platform's own
gateway (metered, `judge-fast` group), and logs every recommendation and its acceptance. Proactive insights appear on the Overview
("12 % 429 on gpt-oss-120b in the last hour; add fallback to gpt-oss-20b" with *Review*). Recommendation quality is evaluated with
the Sprint 3 evaluation platform (faithfulness to docs and data).

### 3.5 Examples in product

Every form keeps a worked example (as the fallbacks editor does today) with a *copy example* action and a link to the relevant
design document (caching, model catalogue, multi-tenancy).

---

## 4. Roadmap placement

| Sprint | Deliverables |
|---|---|
| 2 (in progress) | gateway calls the proxy with a per-tenant/app key (prerequisite for every scope below) |
| 3 | settings hierarchy phase 1: tenant/department/app registry, scoped `gateway_settings` with narrow-only inheritance, scope switcher, team/key `router_settings`, `tenant-admin` and `department-admin`; guided configuration phase 1: settings catalogue, validation, profiles |
| 4 | App control plane integration: well-known document, capability manifest, OAuth2 clients, token exchange, webhooks, admin audit view, tenant-scoped RBAC end to end |
| 5 | configuration copilot and proactive insights (needs the evaluation platform and AIOps signals); organization-level budgets validated or replaced |

Milestones: **M13** settings hierarchy generally available · **M14** AI App control plane integrated through discovery with
gateway-issued credentials · **M15** guided configuration with copilot.

## 5. Risks and open questions

- LiteLLM organization support in the open-source build is less exercised than teams; Sprint 3 starts with a spike. Fallback: tenant =
  team, department = key groups with tags.
- Enterprise-only features (key regenerate, some `premium_field` settings) need either a licence decision or gateway-side equivalents.
- Token exchange is implemented in the gateway because Cognito lacks RFC 8693; KMS-signed gateway JWTs add a signing dependency.
- Copilot safety: propose-only, scope-bound, evaluated; prompts and retrieved documents are versioned.
- Inheritance semantics must be identical in the API and the UI; a single resolver module with unit tests is mandatory.
