# ECS LiteLLM Proxy Module

Runs the LiteLLM proxy as the model gateway behind the AI Gateway:

```text
ECS AI Gateway (FastAPI)  ->  internal ALB  ->  ECS LiteLLM proxy  ->  Groq / Bedrock / OpenAI
```

Resources:

- Private S3 bucket holding `litellm/config.yaml`; the task loads it at start-up via
  `LITELLM_CONFIG_BUCKET_NAME` / `LITELLM_CONFIG_BUCKET_OBJECT_KEY`. Routing, fallbacks and
  budgets change with a config upload and a service redeploy, not an image build.
- Internal ALB (port 80 -> 4000) reachable only from the VPC CIDRs you allow.
- ECS cluster, Fargate task definition and service for `ghcr.io/berriai/litellm`.
- Sidecar ADOT collector so proxy spans land in X-Ray alongside the gateway's.
- Execution role with access to the master-key and provider secrets; task role with
  read access to the config object and Bedrock invoke permissions.
- CloudWatch alarms on target 5xx count and unhealthy hosts.

Inputs of note:

| Variable | Purpose |
|---|---|
| `database_url` | Plain `postgresql://` URL. LiteLLM needs Postgres for virtual keys, team budgets and the spend log. Dev shares the Aurora cluster; prod should use its own database or schema. |
| `master_key_secret_arn` | Secrets Manager ARN of `LITELLM_MASTER_KEY`. Only operators use it; the AI Gateway should get a virtual key generated with `/key/generate`. |
| `provider_secret_arns` | Map of env var name to secret ARN, e.g. `{ GROQ_API_KEY = ... }`. These never reach the AI Gateway task. |
| `config_file_path` | Local path to `litellm/config.yaml`, uploaded by Terraform. |

Outputs: `proxy_url` (feed into the AI Gateway as `LITELLM_PROXY_URL`), `service_security_group_id`
(allow it into the Aurora security group), cluster/service/log group names.

Post-deploy, generate a scoped key for the gateway and store it in Secrets Manager:

```bash
curl -X POST "$PROXY_URL/key/generate" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key_alias":"ai-gateway-dev","team_id":"ai-gateway","max_budget":50,"budget_duration":"30d","models":["llama-3.3-70b-versatile","llama-3.1-8b-instant","judge-fast","chat-default"]}'
```
