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

## Governance built into the gateway layer

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
- `POST /config/update` cannot change keys that are pinned in `litellm/config.yaml` (LiteLLM returns 400). Routing
  (`model_list`, `router_settings`, the OTel callback) stays repository-managed: edit the file, plan/apply
  `ecs-litellm-proxy`, force a new deployment.
- Response caching requires Redis (ElastiCache); the Cache panel is informational until Sprint 5.
- Teams map to tenants (`custom:tenant_id` in Cognito); the roadmap's Sprint 2 item "map tenant → team" wires the
  gateway to send the tenant's team key automatically.

## Verified (dev, 2026-10-02, local proxy)

Settings override validated against served models; provider disable → `/chat` 409 → re-enable; Anthropic credential
stored → provider enabled from source `litellm` → model added with `litellm_credential_name` → test → removed →
credential deleted; team + key created, listed, deleted; MCP server (`https://mcp.deepwiki.com/mcp`, http) registered →
3 tools listed → healthy → removed; guardrail settings listed; `/config/update` on a config-pinned key rejected (as
documented); spend reports returned; `POST /chat/completions` through the passthrough denied (403); audit rows redacted.
