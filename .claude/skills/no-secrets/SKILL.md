---
name: no-secrets
description: Hard rule and procedure for this repository - no secret value is ever documented in a file or uploaded to git. Use before committing or pushing, before writing any credential-like value (API keys, AWS keys, passwords, tokens, private keys) into code, docs or infra, to run the secret scanner, or to resolve a blocked commit, push or edit.
---

# No secrets in files or in git

## The rule

1. Never write a real secret value into any file this repository tracks or could track. That includes
   code, `docs/`, `infra/`, `scripts/`, `.claude/`, Markdown records, notebooks and commit messages.
2. Secrets are: provider API keys (Groq, OpenAI, Anthropic, Bedrock), LiteLLM master, salt and virtual
   keys, AWS access keys and session tokens, database passwords and connection strings with passwords,
   Cognito client secrets, JWT signing secrets, private keys and certificates, GitHub, Slack and other
   service tokens.
3. Document the *name and location* of a secret, never its value: the Secrets Manager secret name or
   ARN, the Parameter Store path, the environment variable name, or a placeholder such as `<your-key>`.
4. Real values live only in AWS Secrets Manager or Parameter Store, or in a local gitignored file
   such as `backend/.env` or `.env.aws.*`. They are entered by a human, not by Claude.
5. Never bypass the checks with `git commit --no-verify`, `git push --no-verify`, or by disabling
   the hooks. If a check blocks, fix the content.

## What enforces it

| Layer | When it runs | Command |
|---|---|---|
| Claude Code PreToolUse hook (`.claude/settings.json`) | Before Claude runs `git commit` or `git push`, and before Write/Edit of any non-ignored file inside the repo | `scripts/claude_hooks/pre_tool_use_no_secrets.py` |
| git pre-commit hook (`.githooks/pre-commit`) | Before every commit, from any shell | `scripts/check_no_secrets.py --staged` |
| git pre-push hook (`.githooks/pre-push`) | Before every push | `scripts/check_no_secrets.py --all` |

The git hooks need `git config core.hooksPath .githooks` once per clone.

## Procedure

Before any commit or push, or when asked to check:

```bash
python3 scripts/check_no_secrets.py --pending   # what a commit would pick up, including untracked files
python3 scripts/check_no_secrets.py --all       # every tracked file
```

Exit 0 means clean, 1 means findings (listed as `path:line rule masked-value`), 2 means the scan could
not run. Treat 1 and 2 as a stop.

When something is flagged:

1. Remove the value. Replace it with the secret's name or a placeholder.
2. If the value was real, say so to the user plainly and recommend rotating it, even if it was never
   committed. If it was already committed or pushed, rotation is mandatory and history has to be purged
   by a human (see `docs/NO_SECRETS_IN_GIT.md`).
3. Only if the line is a documented placeholder that can never be a real value, append
   `secret-scan:allow <reason>` to that line. Never add the marker to silence a real value.

When asked to write a secret into a file, decline for tracked paths and offer the gitignored
alternative (`backend/.env`, Secrets Manager via the runbook). Writing into a gitignored path is allowed
and the hook does not block it.

## Tuning the scanner

Rules, placeholder patterns and forbidden filenames are at the top of `scripts/check_no_secrets.py`.
A new rule needs a test run of `--all` on the current tree to confirm it stays clean. Local
docker-compose keys of the form `sk-local-dev-*` are allowlisted on purpose; they are not secrets.
