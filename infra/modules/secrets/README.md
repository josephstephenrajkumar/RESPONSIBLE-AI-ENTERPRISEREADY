# Secrets Module

Creates Secrets Manager secrets under `<project>-<environment>/` from the `secrets` map in the live configuration,
generating values for `database_master_password`, `jwt_secret` and `litellm_master_key` and placeholders
(`replace-me`, ignored on later applies) for everything else.

Dev secrets:

| Secret | Value | Consumer |
|---|---|---|
| `groq_api_key` | provider key, stored by an operator after apply | LiteLLM proxy task only |
| `litellm_master_key` | generated | LiteLLM proxy (admin), operators |
| `litellm_gateway_key` | stored by an operator: a scoped LiteLLM virtual key (dev currently copies the master key, TD-25) | AI Gateway task |
| `database_master_password` | generated | Aurora, both ECS services |
| `jwt_secret` | generated, unused (Cognito signs tokens) — TD-17 | — |

Outputs: `secret_arns`, `secret_names`, `database_master_password` (sensitive).
