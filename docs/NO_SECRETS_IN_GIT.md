# No Secrets in Git or Documentation

| | |
|---|---|
| Status | Policy in force from 2026-10-03; enforced by hooks in this repository |
| Scope | Every file git tracks or could track, every commit message, every page under `docs/` |
| Related | [CLAUDE.md](../CLAUDE.md), `.claude/skills/no-secrets/SKILL.md`, [AWS_ACCOUNT_AND_PROFILE.md](AWS_ACCOUNT_AND_PROFILE.md), [claude-development-cycle](claude-development-cycle/README.md) |

## 1. Policy

No secret value is documented in this repository or uploaded to git. Documentation records **where** a
secret lives and **what it is called**, never the value.

What counts as a secret:

- Provider API keys: Groq, OpenAI, Anthropic, Bedrock credentials.
- LiteLLM master key, salt key and virtual keys.
- AWS access key IDs, secret access keys and session tokens.
- Database passwords and any connection string that embeds a password.
- Cognito app client secrets, JWT signing secrets, session secrets.
- Private keys, certificates with private material, SSH keys.
- GitHub, Slack, Google and other service tokens.

What is allowed:

- Secret **names** and **locations**: Secrets Manager secret names or ARNs, Parameter Store paths,
  environment variable names.
- Placeholders such as `<your-groq-key>`, `${LITELLM_MASTER_KEY}`, `GROQ_API_KEY=...`.
- Non-secret identifiers: AWS account IDs, IAM user and role names, resource names, regions, URLs.
- The local docker-compose LiteLLM keys `sk-local-dev-*`. They are development placeholders committed on
  purpose and are allowlisted by the scanner.

Where real values live:

| Environment | Store | Who enters it |
|---|---|---|
| AWS dev | Secrets Manager (`responsible-ai-dev-*` secrets), Parameter Store | Release owner, per [AWS_DEV_DEPLOYMENT_RUNBOOK.md](AWS_DEV_DEPLOYMENT_RUNBOOK.md) |
| Local | `backend/.env`, `.env.aws.*` (both gitignored) | Developer |
| CI | Pipeline secret variables | Pipeline owner |

## 2. Enforcement

Three layers run the same scanner, `scripts/check_no_secrets.py` (standard library only).

| Layer | Trigger | Mode | Blocks |
|---|---|---|---|
| Claude Code hook, `.claude/settings.json` | Claude runs `git commit` | `--pending` (staged, unstaged, untracked) | the command |
| Claude Code hook | Claude runs `git push` | `--all` (every tracked file) | the command |
| Claude Code hook | Claude writes or edits a file inside the repo that is not gitignored | `--text` on the new content | the edit |
| git `pre-commit`, `.githooks/pre-commit` | any `git commit` | `--staged` | the commit |
| git `pre-push`, `.githooks/pre-push` | any `git push` | `--all` | the push |

The scanner flags known key formats (AWS, Groq, OpenAI/LiteLLM, Anthropic, GitHub, Slack, Google,
JWTs, private key blocks), credential assignments whose value looks generated (digits plus mixed case,
or long and high entropy), URLs that embed a password, and forbidden filenames (`.env` other than
`.env.example`, `*.pem`, `*.p12`, `*.tfstate`, `id_rsa*`, `credentials`, `infra-inputs-dev.md`).

One-time setup per clone:

```bash
git config core.hooksPath .githooks
python3 scripts/check_no_secrets.py --all      # expect: secret scan: clean
```

The Claude Code hook needs no setup; it is read from the committed `.claude/settings.json`.

## 3. When a check blocks

1. Read the finding: `path:line  rule  masked-value`.
2. Remove the value. Replace it with the secret's name, its store location, or a placeholder.
3. If the value was real and had reached a commit, treat it as leaked (section 4), even if never pushed.
4. Only when the line is a documented placeholder that can never hold a real value, append
   `secret-scan:allow <reason>` to that line.
5. Never use `--no-verify`, never edit the hook to skip a path, never move the value into a commit message.

## 4. If a secret was committed or pushed

1. Rotate it immediately in its source system (Groq console, AWS IAM, LiteLLM key management, Cognito).
   Rotation is not optional: forks, clones and GitHub caches may already hold the value.
2. Update the value in Secrets Manager or the local `.env`, then redeploy the affected service.
3. Purge the value from history (`git filter-repo` or BFG), force-push, and ask every collaborator to
   re-clone. This is a human-run step with a second person reviewing.
4. Record the incident date, the secret name (not value) and the rotation in
   `docs/claude-development-cycle/records/`.

## 5. Maintaining the scanner

Rules, placeholder patterns and forbidden names are declared at the top of `scripts/check_no_secrets.py`.
After changing them, run `--all` on the current tree and confirm it is clean, then run the examples in
`.claude/skills/no-secrets/SKILL.md`. Keep the allowlist narrow: it should name placeholder shapes, not
paths.
