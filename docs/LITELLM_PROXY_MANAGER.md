# LiteLLM Proxy Manager

The **Proxy Manager** tab (role `admin` or `model-admin`; read-only for `policy-manager`) is the single admin
surface for the model gateway. It lets an administrator enable or disable providers and models, store provider
credentials, manage tenants' budgets and virtual keys, register MCP servers, configure proxy-side guardrails, review
routing and spend — all without redeploying and without ever seeing the proxy or its admin key from the browser.

```text
Browser (Cognito JWT)  ->  Gateway  ->  LiteLLM proxy (VPC-internal)
                            |  RBAC (admin / model-admin / policy-manager)
                            |  allow-listed management routes only
                            |  admin key swapped in, secrets redacted in audit
                            |  runtime settings (DB): enable/disable, defaults
```

## How providers were enabled, and how to enable or disable them now

| Layer | What it controls | Where |
|---|---|---|
| **Credential on the proxy** | whether the proxy *can* call the provider | mounted by Terraform (`provider_secret_arns`, e.g. `GROQ_API_KEY`), **or** stored by an administrator in LiteLLM's encrypted credential store from the Providers section, **or** IAM (Amazon Bedrock uses the proxy task role) |
| **Deployment hint** | which env-mounted credentials exist | `LLM_PROVIDERS_ENABLED` on the gateway (`enabled_providers` in Terraform). Dev: `groq,bedrock` |
| **Admin toggle** | hide a provider and reject its models at runtime | Providers → *Disable provider* / *Enable provider* (stored in `gateway_settings.providers.disabled`) |

A provider shows as **enabled** when it has at least one credential source (`env`, `litellm`, `iam`) and is not
disabled by an administrator. Groq is enabled through the Terraform-mounted key; Bedrock through IAM. To enable
Anthropic, OpenAI, Gemini or Mistral **without a deployment**: Providers → enter the API key → *Store in proxy*.
LiteLLM encrypts it with `LITELLM_SALT_KEY` and stores it as credential `<provider>-default`; models added for that
provider reference it by name (`litellm_credential_name`), so the key never appears in model configuration either.

Disabling a provider hides its models from the chat selector and makes `/chat` answer `409 Provider 'x' has been
disabled by an administrator`. Disabling a single model works the same way (Models → ✓/✕ buttons).

## Configuration architecture: bootstrap file vs. runtime settings

LiteLLM refuses runtime changes to any key pinned in its config file. So that administrators can actually *define*
settings, the split is:

| Layer | Contains | Owned by | Changed how |
|---|---|---|---|
| `litellm/config.yaml` (bootstrap) | `model_list` seed, `master_key`, `database_url`, `store_model_in_db`, `return_response_headers`, platform `callbacks: [otel]` | repository (Git review) | edit → plan/apply `ecs-litellm-proxy` (S3) → force new deployment |
| LiteLLM database (runtime) | `router_settings` (retries, timeout, cooldown, fallbacks, strategy), `litellm_settings` (`drop_params`, `request_timeout`, success/failure callbacks + their env vars), `general_settings` fields, cache settings, runtime-added models, credentials, keys, teams, MCP servers, guardrails | administrators via the Proxy Manager | immediately, persisted, audited |
| `backend/app/litellm_runtime_defaults.json` | the baseline router/litellm settings | repository | applied once by the gateway at start-up when the proxy has no router settings; *Re-apply shipped defaults* overwrites on demand |

Verified locally: after restarting the proxy with the bootstrap-only file, the gateway's seed produced retries 2,
timeout 30, cooldown 30 and the fallback chain; a further restart kept them (loaded from the database); a Langfuse
callback was enabled with `environment_variables` and removed again; completions kept working.

## What an administrator can define, per section

| Section | Define / edit |
|---|---|
| Providers | store, replace, remove a provider key (LiteLLM encrypted store); enable / disable provider |
| Models | add from discovery, test, remove; **edit** alias, prices, extra `litellm_params` (e.g. `reasoning_effort`), description; enable / disable; default chat model, judge model, **chat allowlist** |
| Keys & Teams | create / **edit** / delete teams (budget, duration, RPM/TPM, models); generate / **edit** / **rotate** (gateway-side: new key with the same scope, old key deleted — LiteLLM's own `/key/{key}/regenerate` is Enterprise-only) / block / delete keys |
| MCP Servers | register / **edit** (URL, transport, auth, allowed tools) / inspect tools and health / remove |
| Guardrails | add (type, mode, params), **toggle default-on**, **test with sample text**, delete |
| Routing & Settings | **router settings form** (retries, timeout, allowed fails, cooldown, retry-after, strategy, fallbacks), **LiteLLM settings** (`drop_params`, `request_timeout`), **callbacks** (enable any of LiteLLM's callbacks with their env vars, remove), **cache** (Redis connection form from LiteLLM's own field list, test, save, ping, flush), **general settings** (generated form from `/config/list`, saved per field), re-apply shipped defaults, read-only bootstrap file |
| Spend | read-only (LiteLLM's spend log) |

Rotation note: after a rotation LiteLLM's `/key/info` may still return 200 for the deleted key (served from its cache); the proxy rejects the old key immediately and `/key/list` is the source of truth.

Session handling: the frontend now keeps the Cognito refresh token, refreshes the ID token before expiry and on a
401, and shows "Session expired — sign in again" instead of failing every call with *Invalid authentication token*.

## Where provider credentials are stored

| Card shows | Storage | Path to the proxy | Rotation / audit |
|---|---|---|---|
| source `env` (Groq today) | **AWS Secrets Manager** `responsible-ai-<env>/<provider>_api_key`, KMS-encrypted | Terraform mounts it into the **LiteLLM task only** (`secrets` block) | Secrets Manager rotation + CloudTrail; redeploy proxy after rotation |
| source `litellm` ("Store in proxy") | **LiteLLM database** (Aurora, `LiteLLM_CredentialsTable`), encrypted with `LITELLM_SALT_KEY` (itself in Secrets Manager) | browser → API Gateway (TLS) → gateway → proxy over the VPC, forwarded once; the gateway never persists or logs it | replace from the card; audit row `litellm_post /credentials` with the value redacted |
| source `iam` (Bedrock) | no key | proxy task role | IAM |
| planned (Sprint 2) | **AWS Secrets Manager** written by the gateway, read by LiteLLM's `key_management_system: aws_secret_manager` | key never enters the LiteLLM DB | AWS-native; Vault / Key Vault / GCP via the same setting on a dedicated proxy |

"Store in proxy" is therefore the LiteLLM-database path, not Secrets Manager. The Secrets-Manager-backed path and
per-tenant stores are on the roadmap (Sprint 2–3, [MULTI_TENANCY_DESIGN.md](MULTI_TENANCY_DESIGN.md) §4.3).

## LiteLLM's native Admin UI

LiteLLM ships its own console at `<proxy>/ui` (login: `UI_USERNAME`/`UI_PASSWORD` if set, otherwise user `admin` with
the master key; SSO is a LiteLLM enterprise feature). It shows every capability, including ones the Proxy Manager does
not wrap yet.

- Local: http://localhost:4000/ui (master key `sk-local-dev-master-key` from docker-compose).
- AWS dev: the proxy ALB is **VPC-internal** by design, so the UI is not reachable from the internet. Options, in order of
  preference: an SSM Session Manager port-forward through a small bastion or an ECS task in the VPC
  (`aws ssm start-session --document-name AWS-StartPortForwardingSessionToRemoteHost` to the internal ALB, port 80);
  AWS Client VPN; or, later, publishing `/ui` behind API Gateway + Cognito (two logins unless SSO). Do not expose the
  proxy ALB publicly: it carries the master key login.

## Response caching

Not enabled yet (needs Redis). See [RESPONSE_CACHING.md](RESPONSE_CACHING.md) for provisioning ElastiCache and turning
caching on either in `config.yaml` or at runtime from the Cache panel (`POST /cache/settings`, test, ping, flush).

## Sections and the LiteLLM APIs behind them

| Section | What you can do | LiteLLM endpoints (through `/gateway/admin/litellm/*` or curated gateway routes) |
|---|---|---|
| Overview | readiness, counts, callbacks, effective default/judge model, spend by model | `/health/readiness`, `/model/info`, `/credentials`, `/key/list`, `/team/list`, `/v1/mcp/server`, `/guardrails/list`, `/get/config/callbacks`, `/global/spend/models` |
| Providers | enable/disable; store/replace/remove an API key | `GET/POST/PATCH/DELETE /credentials[/{name}]`; gateway settings |
| Models | catalogue (browse, add, test, remove), enable/disable, default and judge model | `/model/info`, `/model/new`, `/model/delete`, `/public/litellm_model_cost_map`, `/model_group/info`; `PUT /gateway/settings` |
| Keys & Teams | tenants (teams) with budgets and model scope; virtual keys with budget, RPM/TPM, expiry; block/unblock/delete | `/team/new|list|delete`, `/key/generate|list|update|block|unblock|delete` |
| MCP Servers | register / inspect tools and health / remove | `GET/POST /v1/mcp/server`, `GET /v1/mcp/tools?server_id=`, `GET /v1/mcp/server/health?server_id=`, `DELETE /v1/mcp/server/{id}` |
| Guardrails | list, add (type, mode, params), delete proxy-side guardrails | `/guardrails/list`, `/guardrails/ui/add_guardrail_settings`, `POST /guardrails`, `DELETE /guardrails/{id}` |
| Routing & Settings | view router settings, callbacks, cache; runtime config update for keys not pinned in `config.yaml` | `/settings`, `/get/config/callbacks`, `/cache/settings`, `/config/yaml`, `POST /config/update` |
| Spend | LiteLLM's spend by model / provider / key / team and recent log entries | `/global/spend/models|provider|keys|teams`, `/spend/logs` |

Everything else in LiteLLM (218 management routes) is reachable through the same governed passthrough if the UI does
not cover it yet — see the allow-list in `backend/app/litellm_admin.py`. Inference routes are deliberately **not**
allowed: model calls must go through `app.llm_client` so they are policy-checked and metered.

## Capability discovery — how the UI knows what LiteLLM can do

**How the current screens were built (engineering time, not runtime).** LiteLLM is self-describing: the proxy serves
`GET /routes` (today 624 routes in 136 families, 218 of them management) and `GET /openapi.json` (request/response
schemas). The eight Proxy Manager sections were derived from those two documents plus the LiteLLM source, and each
section was hand-built against the schemas. The gateway's allow-list (`litellm_admin.ALLOWED_ROUTES`) and the provider
registry (`model_catalog.PROVIDERS`) are therefore **static code**, and a new LiteLLM feature does not appear in the UI
by itself.

**What already adapts at runtime.** Inside each section, option lists come from the proxy, so they track LiteLLM
upgrades without code changes: guardrail types and modes (`/guardrails/ui/add_guardrail_settings`), cache fields
(`/cache/settings`), models and prices (`/model/info`, `/public/litellm_model_cost_map`), MCP tools (`/v1/mcp/tools`),
callbacks (`/get/config/callbacks`), spend reports.

**Target mechanism (roadmap Sprint 3): detect automatically, enable deliberately.**

1. **Capability manifest.** On start-up and on demand the gateway reads `/routes` + `/openapi.json`, groups routes
   into families (`model`, `key`, `team`, `v1/mcp`, `guardrails`, `config`, `cache`, `credentials`, `organization`,
   `tag`, `access_group`, `auto_router`, `workflows`, `schedule`, …), and compares them with (a) the allow-list and
   (b) the sections the UI covers. The result is stored with the LiteLLM build identifier and shown on the Overview as
   *Covered / Allowed-but-uncurated / Not allowed (new)*. A change after a proxy upgrade produces an audit event and a
   banner, so an upgrade of the `main-stable` image is noticed the same day.
2. **Dynamic allow-list.** Administrators can enable a newly detected management family from that panel; the gateway
   persists it in `gateway_settings` (`litellm.allowed_routes_extra`) and the passthrough honours it. Inference routes
   remain permanently excluded (metering and policy must not be bypassed). This keeps a human decision between "LiteLLM
   added X" and "our tenants can call X".
3. **Schema-driven explorer.** For allowed routes without a curated screen, the UI renders a form from the OpenAPI
   request schema (the same way the guardrail *params* box works today) so new capabilities are usable immediately;
   curated screens follow when a capability earns one.
4. **Dynamic provider registry.** `GET /public/providers/fields` returns every provider LiteLLM supports (158 today)
   with display name, `litellm_provider` and credential fields (`api_key`, `api_base`, region, …). The registry moves
   from code to this endpoint; our governance overlay (credential source, enabled flag, tenant scope) stays.
5. **Version pinning.** Pin the proxy image to a release tag instead of the floating `main-stable`, so capability
   diffs correspond to deliberate upgrades (TD-27).



- **RBAC**: writes require `admin` or `model-admin`; reads are open to `policy-manager`, `finops`, `aiops` through the
  overview/catalogue endpoints. `/auth/me` exposes `permissions.manage_models`.
- **Allow-list**: `litellm_admin.ALLOWED_ROUTES` — method + path regex. Unknown or inference routes return 403.
- **Audit**: every write is a `policy_audit_events` row (`litellm_post`, `litellm_delete`, `setting_changed`,
  `model_added`, …) with the actor and a redacted body: keys, secrets, tokens, `credential_values`, `auth_value` are
  replaced by `***` before anything is stored.
- **Credential boundary**: provider keys travel browser → gateway → proxy once, over TLS/VPC, and are stored only in
  LiteLLM's database (encrypted). The gateway never persists or logs them. Bedrock needs no key at all.
- **Runtime settings** live in the application database (`gateway_settings`), layered over environment defaults, so an
  administrator's choices survive restarts and are visible to every gateway task within 15 seconds.

## Operational notes

- The gateway currently manages the proxy with the LiteLLM **master key** in dev (TD-25). Generate a scoped key in
  *Keys & Teams*, store it in `responsible-ai-dev/litellm_gateway_key`, and point `LITELLM_ADMIN_API_KEY` at a key with
  admin rights before production.
- `POST /config/update` cannot change keys pinned in `litellm/config.yaml` (LiteLLM returns 400); that is why the
  file is bootstrap-only and router/litellm/cache/general settings live in the proxy database (see *Configuration
  architecture*).
- Response caching requires Redis (ElastiCache); the Cache panel is informational until Sprint 5.
- MCP server names must be `[A-Za-z0-9_]` only — LiteLLM uses the name as the tool prefix (`<server>-<tool>`) and
  rejects hyphens with `400 Server name cannot contain '-'`. The form enforces this.
- Teams map to tenants (`custom:tenant_id` in Cognito); the roadmap's Sprint 2 item "map tenant → team" wires the
  gateway to send the tenant's team key automatically.

## Verified (dev AWS, 2026-10-02, gateway image `7d16fb5`)

Through the public API Gateway with a temporary `admin` user: overview (readiness healthy, 5 models, callbacks `otel`);
judge model overridden to `nova-micro` and reset; **Bedrock disabled → `/chat` for `nova-micro` returned
`409 Provider 'bedrock' has been disabled by an administrator` and the selector dropped the Bedrock group → re-enabled**;
Anthropic credential stored → provider enabled from source `litellm` → model added with `litellm_credential_name` →
test returned the provider's 401 (dummy key) → model and credential removed; team `smoke-tenant` ($5/30d) and key
`smoke-key` ($1/30d, 30 rpm) created, listed and deleted; MCP server `deepwiki_smoke` registered → 3 tools listed →
healthy → removed; guardrails listed; `/config/update` on a config-pinned key rejected (400, as documented); LiteLLM
spend by model returned; `POST /chat/completions` via the passthrough denied (403).

## Verified (dev, 2026-10-02, local proxy)

Settings override validated against served models; provider disable → `/chat` 409 → re-enable; Anthropic credential
stored → provider enabled from source `litellm` → model added with `litellm_credential_name` → test → removed →
credential deleted; team + key created, listed, deleted; MCP server (`https://mcp.deepwiki.com/mcp`, http) registered →
3 tools listed → healthy → removed; guardrail settings listed; `/config/update` on a config-pinned key rejected (as
documented); spend reports returned; `POST /chat/completions` through the passthrough denied (403); audit rows redacted.
