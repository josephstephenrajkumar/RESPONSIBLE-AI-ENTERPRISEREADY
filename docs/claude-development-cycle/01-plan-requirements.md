# PLAN: Requirements

## Purpose

Turn a request into an auditable, testable change proposal before Claude edits the repository.

## Required Input

The requester supplies:

- business outcome and user or operator affected;
- in-scope behavior and explicit non-goals;
- environment: local, dev, stage, or production;
- data classification and retention expectations;
- security, privacy, safety, fairness, and governance constraints;
- acceptance criteria and rollback expectations;
- whether code, infrastructure, documentation, or only analysis is allowed.

Claude should inspect the nearest owning implementation, neighboring tests, and current documentation. It should not map the whole repository unless the change is cross-cutting.

## Requirements Record

Use this structure in the plan:

```text
Request:
Owner and users:
Environment:
In scope:
Out of scope:
Functional requirements:
Non-functional requirements:
Responsible-AI requirements:
Security and privacy constraints:
Data and audit impact:
Dependencies:
Acceptance criteria:
Rollback or recovery:
Allowed actions:
Open questions:
```

Each requirement must be observable. Replace vague statements such as "make it safe" with checks such as "framework mode redacts detected sensitive values before the provider call and records only permitted audit metadata."

## Project Anchors

For this repository, identify whether the request affects:

- `backend/app/main.py` and the `/chat` request path;
- `backend/app/framework_mode/` privacy, safety, tracing, or evaluation behavior;
- `backend/app/responsible_ai/` code-mode evaluators;
- `backend/app/policy_governance.py` or policy storage and lifecycle;
- `backend/app/database.py` audit and violation persistence;
- `frontend/src/` API calls and user-visible governance state;
- `infra/` or `deploy.sh` deployment behavior;
- existing documents such as the architecture, test plan, and AWS runbook.

## PLAN Gate

A human approves the plan when the affected owner, acceptance checks, data handling, and non-goals are explicit. No implementation begins when a security or policy decision is still hidden in an open question.
