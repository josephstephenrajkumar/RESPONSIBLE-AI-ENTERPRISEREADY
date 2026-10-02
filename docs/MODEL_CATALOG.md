# Model Catalogue — providers and models through LiteLLM

The gateway can serve any model from any provider LiteLLM supports. Administrators manage this from the
**Configuration → Model Catalogue** screen; the chat screen's model selector then shows the configured models
grouped by provider. This page documents what LiteLLM exposes, how the gateway wraps it, and how to enable a
new provider.

```text
Chat screen            Admin screen (Configuration → Model Catalogue)
  model selector         providers · available models · add / test / remove
        |                        |
        v                        v
GET /gateway/models      GET  /gateway/catalog
                         GET  /gateway/catalog/providers/{provider}/available
                         POST /gateway/catalog/models
                         POST /gateway/catalog/models/{name}/test
                         DELETE /gateway/catalog/models/{id}
        |                        |
        v                        v
                 LiteLLM proxy (model gateway)
   /model/info · /model_group/info · /public/litellm_model_cost_map · /model/new · /model/delete
        |
        v
   Groq (API key) · Amazon Bedrock (IAM role) · Anthropic / OpenAI / Gemini / Mistral (API keys)
```

## What LiteLLM exposes

| LiteLLM endpoint | Used for | Notes |
|---|---|---|
| `GET /model/info` | the configured deployments: name, `litellm_params.model` (`provider/model`), `model_info` (provider, costs per token, context limits, `db_model`) | authenticated; a virtual key sees only its models |
| `GET /model_group/info` | model groups such as `chat-default`, `judge-fast` | groups are defined in `litellm/config.yaml` |
| `GET /public/litellm_model_cost_map` | discovery: every model LiteLLM can price, with `litellm_provider` and `mode` | public; ~3,300 chat models across providers |
| `POST /model/new` | add a deployment at runtime | persisted in Postgres when `general_settings.store_model_in_db: true`; credentials encrypted with `LITELLM_SALT_KEY` |
| `POST /model/delete` | remove a runtime-added deployment | models from `config.yaml` cannot be deleted at runtime |
| `GET /health?model=<name>` | provider-side health of one deployment | the admin UI uses a metered test completion instead so cost and latency are shown |

Two proxy settings make this work (`litellm/config.yaml`, `infra/modules/ecs-litellm-proxy`):

```yaml
general_settings:
  store_model_in_db: true      # runtime-added models survive restarts and are merged with config.yaml
```

```text
STORE_MODEL_IN_DB=True
LITELLM_SALT_KEY=<secret>      # generated once (responsible-ai-dev/litellm_salt_key); never rotate while the DB exists
```

## How the gateway wraps it

`backend/app/model_catalog.py` adds the governance layer:

- **Provider registry** (fixed): `groq`, `bedrock`, `anthropic`, `openai`, `gemini`, `mistral`, each with its LiteLLM
  route prefix, credential type (`api_key` env var or `iam`) and which price-map providers it covers.
- **Enablement** comes from the gateway setting `LLM_PROVIDERS_ENABLED` (Terraform `enabled_providers`), which must
  mirror the credentials the *proxy* holds. Disabled providers are shown with instructions, not hidden.
- **Explicit models, no wildcards**: administrators add specific models. A `provider/*` wildcard route would let any
  model be called and defeat budgets and the allowlist.
- **Credential boundary**: a new model's `litellm_params` reference `os.environ/<KEY>` (or no key for Bedrock, which
  uses the proxy task role). The UI never accepts or transmits a provider key.
- **Discovery**: LiteLLM's price map filtered by provider and `mode: chat`. For Bedrock the gateway also calls
  `bedrock:ListInferenceProfiles` / `ListFoundationModels` in `BEDROCK_REGION` and shows only ids that are actually
  invokable there (`apac.*` / `global.*` inference profiles and on-demand base models).
- **Test**: one small completion (`max_tokens=64`) through the normal client, recorded in `llm_usage_events` with
  purpose `catalog_test`, so the FinOps dashboard shows it and the result includes served model, latency and cost.
- **Audit**: adds and removals are written to `policy_audit_events` (`model_added`, `model_removed`) with the actor.

Roles: `admin` and `model-admin` can add, test and remove; `policy-manager` can browse. `/auth/me` returns
`permissions.manage_models`.

## Chat screen

`GET /gateway/models` returns `models` (flat), `by_provider` (grouped) and `details`. The selector renders one
`<optgroup>` per provider. `LLM_ALLOWED_MODELS` (gateway) and the virtual key's `models` scope (proxy) still apply:
a model can be in the catalogue but excluded from chat.

## Enabling a provider

| Provider | Credential | Steps |
|---|---|---|
| Groq | `GROQ_API_KEY` | already enabled in dev |
| Amazon Bedrock | proxy task role (`bedrock:InvokeModel`, `InvokeModelWithResponseStream`) | enabled in dev; add models by inference-profile id, e.g. `apac.amazon.nova-micro-v1:0`, `apac.anthropic.claude-3-haiku-20240307-v1:0` |
| Anthropic | `ANTHROPIC_API_KEY` | 1) `aws secretsmanager put-secret-value --secret-id responsible-ai-dev/anthropic_api_key --secret-string ...` 2) uncomment `ANTHROPIC_API_KEY` in `infra/live/dev/ecs-litellm-proxy/terragrunt.hcl` `provider_secret_arns` 3) add `"anthropic"` to `enabled_providers` in `infra/live/dev/ecs-ai-gateway/terragrunt.hcl` 4) plan/apply both modules |
| OpenAI | `OPENAI_API_KEY` | same steps with `openai_api_key` / `OPENAI_API_KEY` / `"openai"` |
| Gemini, Mistral | `GEMINI_API_KEY`, `MISTRAL_API_KEY` | add the secret to `infra/live/dev/secrets/terragrunt.hcl` first, then the same steps |

Locally: put the key in `backend/.env` (compose passes it to the LiteLLM container) and set
`LLM_PROVIDERS_ENABLED=groq,anthropic` for the backend. Bedrock locally needs AWS credentials inside the proxy
container (not configured by default).

## Governance notes

- Adding a model is a cost decision: pricing is shown from LiteLLM's price map before adding, and every call is
  metered. Use LiteLLM key/team budgets to cap spend per consumer (roadmap Sprint 2).
- `config.yaml` remains the baseline (default chat model, judge group, fallbacks). Runtime-added models are for
  evaluation and gradual rollout; promote them to `config.yaml` once they are permanent.
- Default and judge models are environment settings (`LLM_DEFAULT_MODEL`, `LLM_JUDGE_MODEL`); the catalogue marks
  them but does not change them.
