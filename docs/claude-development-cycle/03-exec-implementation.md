# EXEC: Implementation

## Purpose

Implement the approved design in small, reviewable changes with Claude operating as an accountable coding assistant.

## Before Editing

Claude records:

- the approved requirement and design references;
- the concrete file and symbol being changed;
- one falsifiable local hypothesis;
- the cheapest focused check that could disconfirm it;
- files explicitly excluded from the change.

Claude reads nearby code and tests, then edits only the smallest required slice. It must not fabricate test fixtures that contain real personal data or secrets.

## Implementation Rules

- Preserve public API contracts unless the approved design changes them.
- Validate user input at the schema or boundary that owns it.
- Keep authorization checks server-side; frontend visibility is not authorization.
- Keep privacy redaction before downstream LLM processing where required.
- Keep safety blocking and output validation explicit and testable.
- Use structured persistence and telemetry APIs rather than string-parsing logs.
- Avoid unrelated refactors, generated metadata, dependency churn, and speculative infrastructure.
- Never commit credentials, `.env` files, database files, provider responses, or raw sensitive prompts.
- Never write a secret value into any file, including documentation and records. `scripts/check_no_secrets.py`
  runs before every commit, push and Claude edit; a finding is a stop, not something to bypass with `--no-verify`
  ([NO_SECRETS_IN_GIT.md](../NO_SECRETS_IN_GIT.md)).
- Do not run `apply`, `destroy`, image pushes, or production commands as part of implementation.

## Change Sequence

1. Make one focused edit.
2. Run the cheapest relevant check immediately.
3. Repair only the same slice if that check fails.
4. Add or update focused tests and documentation.
5. Review the diff for scope, secrets, policy impact, and rollback.
6. Summarize changed files and remaining limitations.

## EXEC Gate

The implementation is ready for test when the approved behavior exists, focused checks pass, no unauthorized files changed, and the human reviewer understands any migration or operational action still required.
