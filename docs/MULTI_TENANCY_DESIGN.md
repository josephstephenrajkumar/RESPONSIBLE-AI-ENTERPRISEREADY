# Multi-Tenancy Design

Goal: one AI Gateway serves many tenants with separated data, configuration, credentials, budgets and policies — and
tenants may choose different operating models (for example, one keeps provider keys in LiteLLM's store, another
requires AWS Secrets Manager, a third requires a dedicated proxy). This document describes the tenancy model, what is
already in place, the gaps, and the target design. Delivery is scheduled in [ROADMAP.md](ROADMAP.md).

## 1. Tenancy model

```text
Tenant (Cognito custom:tenant_id, or X-Tenant-Id for service clients)
  └─ Applications / agents (client_id, agent_id)  ──  LiteLLM Team (= tenant) ─ virtual keys (= applications)
       └─ Users (Cognito users, groups: admin / tenant-admin / policy-manager / finops / aiops)
```

| Concept | Gateway (this repo) | LiteLLM proxy |
|---|---|---|
| Tenant | `tenant_id` on users, audit, violations, usage; per-tenant settings namespace | **Team** (budget, model scope, RPM/TPM, tags, guardrails, callbacks, MCP access groups) |
| Application | `client_id` / `agent_id` | **Virtual key** inside the team (own budget/limits) |
| Tenant admin | new role `tenant-admin` (manage own tenant only) | team admin (`team_member_permissions`) |
| Platform admin | `admin` / `model-admin` | master / admin key |

## 2. Isolation tiers (choose per tenant)

| Tier | Shared | Dedicated | Typical tenant |
|---|---|---|---|
| **T1 Logical** (default) | gateway, proxy, Aurora, Redis | LiteLLM team, keys, per-tenant settings, cache namespace, tags | internal business units, pilots |
| **T2 Dedicated proxy** | gateway, Aurora cluster | LiteLLM ECS service + config + database/schema, own `key_management_system` (e.g. Vault), own Redis | regulated or high-volume tenants; tenants needing a different secret manager than the shared proxy |
| **T3 Dedicated account** | nothing (shared code only) | full stack via Terragrunt in another AWS account | sovereign / contractual isolation |

The gateway routes a tenant to its tier through tenant configuration (`tenant.proxy_url`, `tenant.proxy_key_secret`);
T1 is the shared proxy. Tiers coexist behind one API and one frontend.

## 3. What exists today

- Tenant attribution end to end: Cognito `custom:tenant_id` → `AuthenticatedUser.tenant_id` → `audit_events`,
  `guardrail_violations`, `llm_usage_events`; FinOps breaks spend down by tenant; LiteLLM receives
  `metadata.tags=[tenant:<id>, ...]` and `user` for its own spend log.
- Proxy Manager manages LiteLLM **teams and keys** (the tenant/application objects) and global provider enablement.
- Model groups and allow-lists exist but are global; `gateway_settings` is global; safety policies are global.

## 4. Gaps and target design

### 4.1 Request path: the gateway calls the proxy *as the tenant*

Today the gateway uses one LiteLLM key for everyone. Target: resolve the tenant's **team virtual key** per request
(cache: tenant → key, loaded from Secrets Manager `responsible-ai-<env>/tenants/<tenant>/litellm_key` or LiteLLM key
store) and send it as the bearer. Effects, all enforced by the proxy: team budget and RPM/TPM, team model scope
(a tenant can only call models assigned to its team), team guardrails and callbacks, spend attributed to the team.
Judge calls use the same key so evaluation spend lands on the tenant.

### 4.2 Per-tenant configuration

`gateway_settings` keys gain a tenant namespace: `tenant:<id>:chat.default_model`, `tenant:<id>:chat.judge_model`,
`tenant:<id>:providers.disabled`, `tenant:<id>:models.disabled`, `tenant:<id>:credential_store`,
`tenant:<id>:cache_namespace`, `tenant:<id>:isolation_tier`, `tenant:<id>:proxy_url`. Resolution order:
tenant override → platform override → environment default. The Proxy Manager gets a **tenant selector**; `tenant-admin`
sees only their tenant.

Extended in [PROXY_MANAGER_ENTERPRISE_DESIGN.md](PROXY_MANAGER_ENTERPRISE_DESIGN.md) §1 to a full hierarchy (tenant → department → application → request) mapped to LiteLLM organization → team → key, with narrow-only inheritance, and in §2 to the App control plane integration and gateway-issued credentials.

### 4.3 Credentials per tenant and per store

LiteLLM resolves a model's credential three ways, and they can be mixed inside one proxy:

| Store | Reference in model config | Who can use it |
|---|---|---|
| LiteLLM DB (encrypted with `LITELLM_SALT_KEY`) | `litellm_credential_name: <tenant>-<provider>` | tenants who accept proxy-managed secrets |
| AWS Secrets Manager (via `general_settings.key_management_system: aws_secret_manager`) | `os.environ/<SECRET_NAME>` resolved from Secrets Manager; prefix per tenant (`responsible-ai-<env>/tenants/<tenant>/…`) with IAM scoped to the prefix | tenants who require AWS-native rotation, KMS and CloudTrail |
| Environment (Terraform-mounted) | `os.environ/<VAR>` | platform-shared providers (today: Groq) |
| HashiCorp Vault / Azure Key Vault / GCP Secret Manager | `key_management_system` is **one per proxy instance** | tenants needing these run on a **T2 dedicated proxy** |

Models are **team-scoped** (`model_info.team_id` / `access_via_team_ids`, `team_public_model_name`), so a tenant's
credential is only reachable through that tenant's models and keys. The Providers card shows, per tenant, which store
holds the credential and where (provenance), and "Store" writes to the tenant's chosen store.

### 4.4 Data separation in the gateway database

- Every tenant-owned table carries `tenant_id` (already: audit, violations, usage; add: `safety_policies`,
  `policy_audit_events`, `gateway_settings`).
- Reads are filtered by the caller's tenant unless the caller is a platform `admin`/`finops`/`aiops`; Postgres
  **row-level security** policies back the application filter so a bug cannot leak across tenants.
- Reports: `/reports/*` accept `tenant_id` for platform roles and force the caller's tenant otherwise; exports are
  per tenant.
- T2/T3 tenants may additionally get their own schema or database (Aurora supports both in the same cluster).

### 4.5 Policies, guardrails, MCP, caching per tenant

- Safety policies: tenant-scoped ownership and activation (roadmap Sprint 4); platform policies apply to all, tenant
  policies only to that tenant.
- Proxy-side guardrails: attach per team (`guardrails` on team/key) so a tenant can require, say, Bedrock Guardrails.
- MCP servers: LiteLLM `mcp_access_groups` per team; a tenant sees and calls only its servers/tools.
- Cache: per-tenant namespace/prefix (never share cached answers across tenants); or caching off for a tenant.

### 4.6 Chargeback

`llm_usage_events` by tenant (already) reconciled against LiteLLM `/global/spend/report?group_by=team`; monthly export
per tenant; AWS cost-allocation tags for T2/T3 dedicated resources.

## 5. Delivery

| Step | Sprint | Outcome |
|---|---|---|
| Tenant → team mapping; gateway calls proxy with the tenant key; team-scoped models | 2 | budgets, limits and model scope enforced per tenant |
| Tenant settings namespace + tenant selector in Proxy Manager; `tenant-admin` role | 3 | per-tenant defaults, enablement, credential store choice |
| Secrets Manager-backed credentials with per-tenant prefixes; mixed stores in one proxy | 2–3 | one tenant on LiteLLM DB, another on Secrets Manager |
| Tenant-scoped policies, guardrails, MCP access groups; `tenant_id` + RLS on all tables; tenant-scoped reports/exports | 4 | data and policy separation (T1 complete) |
| T2 dedicated proxy module (per-tenant ECS service/config/DB, own key management system) | 5 | tenants with Vault/Key Vault or isolation requirements |
| Per-tenant cache namespaces; chargeback exports | 5–6 | cost and cache isolation |
