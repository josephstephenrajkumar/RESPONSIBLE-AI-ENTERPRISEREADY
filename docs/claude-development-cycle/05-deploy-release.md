# DEPLOY: Release and Operations

## Purpose

Describe a controlled release path. This document is guidance only; creating it does not authorize or execute deployment.

## Preconditions

Before any deployment, a human release owner confirms:

- the intended AWS account, profile, region, and environment;
- the change is approved and tested;
- secrets exist only in approved secret stores, and `python3 scripts/check_no_secrets.py --all` reports clean
  ([NO_SECRETS_IN_GIT.md](../NO_SECRETS_IN_GIT.md));
- database migrations and backward compatibility are understood;
- infrastructure plans show the intended resources and no unexpected destruction;
- the backend image and frontend artifact are traceable to the reviewed change;
- rollback, monitoring, and incident contacts are ready;
- responsible-AI policy changes have the required governance approval.

Never put `GROQ_API_KEY`, LiteLLM keys, AWS credentials, database passwords, session tokens, or JWT secrets in this folder or any chat prompt.

## Project Release Order

Follow the current AWS runbook and verify every plan before applying:

```text
1. network
2. secrets
3. cognito
4. aurora-postgres
5. ecr
6. build and push backend image (linux/amd64, tagged with the commit sha; pin image_tag)
7. ecs-litellm-proxy
8. ecs-ai-gateway
9. api-gateway
10. frontend-s3-cloudfront (then build/upload the frontend and add the CloudFront origin to cognito, api-gateway and ecs-ai-gateway)
11. observability
```

Apply saved plans that have been read (`plan -out` → review → `apply <file>`), never `-auto-approve` against an existing environment.

The repository's infrastructure is not assumed complete merely because a Terragrunt directory exists. Confirm each module has reviewed Terraform implementation, valid inputs, outputs, state configuration, and a successful plan in the target environment.

## Deployment Verification

After an approved deployment, the release owner verifies:

- `/health` and root metadata;
- authentication and authorization behavior;
- `/observability` and trace export;
- `/gateway/health` reports `mode: proxy`, the default model served, and `application_holds_provider_key: false`;
- the gateway task definition mounts `LITELLM_API_KEY` only;
- FinOps and AIOps reports populated by the smoke-test calls with `cost_source: litellm`;
- `/policy` and policy lifecycle state;
- benign code and framework chat flows;
- synthetic privacy redaction;
- synthetic blocked safety input with no provider call;
- audit and violation records without raw sensitive values;
- frontend loading, API origin, and user-visible error handling;
- CloudWatch logs, alarms, ECS task health, API Gateway responses, and database connectivity.

Record account, region, commit or image digest, time, checks, result, and rollback decision. Do not record secrets or raw user prompts.

## Rollback

Stop the release and use the approved rollback path when health checks, policy enforcement, authentication, data integrity, or error rates regress. Rollback may mean restoring the prior image, frontend artifact, configuration, or database-compatible migration; it is not automatically `destroy`.

## DEPLOY Gate

Deployment is complete only after post-deploy verification and human sign-off. Claude may prepare commands or review plans, but it must not claim deployment success without observed evidence from the target environment.
