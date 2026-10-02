# Claude AI Development Cycle

This folder defines a Claude-assisted, human-approved delivery cycle for the Responsible AI EnterpriseReady project.

The cycle is:

```text
PLAN -> GOAL -> EXEC -> TEST -> DEPLOY
  ^                         |
  |------ learn and refine -|
```

The documents are project-specific. They are not application code, Terraform code, deployment scripts, or a substitute for approval.

## Scope

The current repository is a synchronous Responsible AI Gateway:

```text
React/Vite -> FastAPI AI Gateway -> LiteLLM proxy -> Groq / Bedrock
                    |
                    +-> privacy and safety checks
                    +-> Ragas / TruLens judges (via the proxy)
                    +-> policy governance, audit and usage metering
                    +-> telemetry and tracing
```

The AWS shape is CloudFront/S3, API Gateway, two ECS Fargate services (gateway and LiteLLM proxy), Aurora PostgreSQL, Cognito, Secrets Manager, and observability services; dev is deployed in account 767141477889 (see `docs/aws-snapshots/`). The runbook identifies the deployment order; every apply uses a reviewed saved plan.

## How Claude Participates

Claude may inspect repository files, explain behavior, propose a change, write a small implementation, and run approved local checks. Claude must:

- state the current hypothesis and affected files before editing;
- preserve existing APIs and responsible-AI controls unless the requirement changes them;
- never invent secrets, credentials, policy approvals, test evidence, or deployment results;
- avoid sending prompts, audit data, or secrets to external services unless explicitly authorized;
- keep code, infrastructure, documentation, and generated artifacts separate;
- stop for human review at policy, security, data-model, infrastructure, and production gates;
- report exactly what was changed, tested, skipped, and remains risky.

## Stage Documents

1. [PLAN: Requirements](01-plan-requirements.md)
2. [GOAL: Solution Design](02-goal-solution-design.md)
3. [EXEC: Implementation](03-exec-implementation.md)
4. [TEST: Verification](04-test-verification.md)
5. [DEPLOY: Release and Operations](05-deploy-release.md)

## Operating Rule

A stage is complete only when its entry criteria, outputs, and approval gate are satisfied. A failed check returns work to the smallest earlier stage that owns the defect. Production deployment is never implied by a successful local test.
