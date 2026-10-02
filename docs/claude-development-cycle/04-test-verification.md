# TEST: Verification

## Purpose

Produce evidence that the change meets its requirements without confusing local success with deployment readiness.

## Test Layers

### Focused checks

Run the narrowest test for the changed behavior first. Examples:

- backend import or targeted test for an API or evaluator change;
- a framework-mode privacy case with synthetic email and SSN values;
- an unsafe prompt case proving safety blocks before an LLM call;
- a benign education case proving the policy does not over-block;
- a policy lifecycle case proving approval and activation rules;
- a frontend build for a UI or API integration change.

### Repository regression checks

The current documented baseline is:

```bash
python -m compileall backend/app
npm --prefix frontend run build
```

Run these from the repository root after focused checks when the change warrants them. Use the existing `docs/TEST_PLAN.md` for endpoint and local runtime checks.

### Security and responsible-AI checks

Confirm as applicable:

- unauthenticated access is rejected when `AUTH_REQUIRED=true`;
- policy-management endpoints enforce manager authorization;
- sensitive values are redacted before provider processing;
- blocked inputs do not trigger an LLM call;
- output violations are handled according to policy;
- audit entries are user-scoped and do not expose raw sensitive input;
- trace and error fields do not contain credentials or raw prompts;
- CORS and frontend origins match the intended environment.

## Evidence Record

```text
Requirement:
Command or test:
Environment:
Result:
Relevant output:
Known limitation:
Reviewer:
Date:
```

Use synthetic data. Do not paste secrets or customer data into test output, Claude context, issues, or commits.

## TEST Gate

A human accepts the change when every acceptance criterion has evidence or an explicitly recorded exception, known failures are triaged, and release risk is understood. A build passing alone is not sufficient for a policy, security, data, or deployment change.
