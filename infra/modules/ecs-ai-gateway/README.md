# ECS AI Gateway Module

Resources:

- ECS cluster and Fargate service for the FastAPI AI Gateway (policy enforcement, metering)
- Task definition using the ECR backend image, with an ADOT collector sidecar
- Internal ALB and target group (health check `/health`)
- Execution role for Secrets Manager; task role for CloudWatch and X-Ray
- CloudWatch log group

LLM egress is configured by `llm_gateway_mode`:

| Mode | Behaviour | Secrets mounted |
|---|---|---|
| `proxy` (default) | All model calls go to `litellm_proxy_url` (the `ecs-litellm-proxy` module's internal ALB) with the LiteLLM virtual key. | `LITELLM_API_KEY` from `litellm_api_key_secret_arn` |
| `direct` | Break-glass: the gateway calls Groq itself. | `GROQ_API_KEY` from `groq_api_key_secret_arn` |

Other inputs: `llm_default_model`, `llm_judge_model` (use `judge-fast` to cut evaluation spend),
`llm_allowed_models` (comma-separated allowlist), `finops_monthly_budget_usd` (FinOps budget gauge).

Deployment order: apply `ecs-litellm-proxy` first, generate the gateway's virtual key with
`/key/generate`, store it in the `litellm_gateway_key` secret, then apply this module.

Planned: autoscaling policy; security-group-referenced ingress instead of CIDR (see `docs/TECH_DEBT.md`).
