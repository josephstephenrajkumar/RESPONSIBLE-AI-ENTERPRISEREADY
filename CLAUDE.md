# Responsible AI EnterpriseReady - project rules for Claude

## Secrets: hard rule

No secret value is ever documented in this repository or uploaded to git.

- Never write a real credential into any tracked or trackable file: code, `docs/`, `infra/`, `scripts/`,
  `.claude/`, records, notebooks, commit messages. Credentials include provider API keys (Groq, OpenAI,
  Anthropic), LiteLLM master/salt/virtual keys, AWS access keys and session tokens, database passwords,
  Cognito client secrets, JWT secrets, private keys and any service token.
- Document the name and location of a secret, never its value: Secrets Manager name or ARN, Parameter
  Store path, env var name, or a placeholder like `<your-key>`.
- Real values live only in AWS Secrets Manager / Parameter Store or in gitignored local files
  (`backend/.env`, `.env.aws.*`), and are entered by a human.
- Enforcement: a PreToolUse hook in `.claude/settings.json` runs `scripts/check_no_secrets.py` before
  `git commit` / `git push` and before Write/Edit of repo files; `.githooks/pre-commit` and
  `.githooks/pre-push` do the same for any shell (`git config core.hooksPath .githooks` once per clone).
- If blocked: remove the value, replace with a placeholder or reference, and tell the user. Never use
  `--no-verify` or disable the hooks. Use the `/no-secrets` skill for the full procedure, and
  `docs/NO_SECRETS_IN_GIT.md` for the policy and incident steps.

## Working conventions

- Follow `docs/claude-development-cycle/` (PLAN, GOAL, EXEC, TEST, DEPLOY) and stop at its human gates.
- AWS dev is account 767141477889, region ap-southeast-1, project `responsible-ai`; see
  `docs/AWS_ACCOUNT_AND_PROFILE.md`. Run the identity check before any Terragrunt command.
