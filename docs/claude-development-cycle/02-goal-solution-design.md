# GOAL: Solution Design

## Purpose

Convert approved requirements into a minimal design that fits the existing architecture and can be verified locally.

## Design Sequence

1. Identify the direct controller of the behavior.
2. Describe the request and response flow.
3. Choose the smallest compatible change.
4. Define failure behavior and safe defaults.
5. Define telemetry, audit, and policy effects.
6. Define tests before implementation.
7. Identify migration, compatibility, and rollback needs.

## Design Record

```text
Goal:
Current behavior:
Proposed behavior:
Owning components:
Data flow:
API or schema changes:
Policy and safety behavior:
Privacy and retention behavior:
Authentication and authorization:
Observability and audit events:
Failure and fallback behavior:
Compatibility impact:
Test strategy:
Rollback strategy:
Human approvals:
```

## Project Design Constraints

- Keep interactive chat synchronous unless the approved requirement explicitly introduces an asynchronous workflow.
- Preserve input privacy checks before provider calls and output checks before responses leave the gateway.
- Treat policy states as governed transitions: `draft`, `review`, `approved`, `active`, and `deprecated`.
- Do not log raw prompts, sensitive values, credentials, tokens, or provider secrets.
- Keep local development defaults distinct from AWS settings and authenticated production behavior.
- Prefer existing FastAPI, Pydantic, SQLAlchemy, React/Vite, telemetry, and Terragrunt patterns.
- Treat TruLens/Ragas-style placeholders and incomplete infrastructure modules as explicit limitations, not completed capabilities.

## Claude Design Prompt

> Explain the proposed change in terms of the current repository. Name the file and symbol that own the behavior, the smallest compatible edit, the observable acceptance checks, and one failure mode. Do not write code until the design is approved.

## GOAL Gate

A human approves the design when data flow, safety behavior, operational impact, and test evidence are defined. For policy, authentication, database, or infrastructure changes, approval must include the relevant owner rather than relying on Claude's interpretation alone.
