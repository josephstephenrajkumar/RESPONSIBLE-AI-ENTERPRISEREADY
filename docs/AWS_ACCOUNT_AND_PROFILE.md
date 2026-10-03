# AWS Account, Project Name and Profile

| | |
|---|---|
| Status | Verified 2026-10-03 against the live dev account |
| Scope | Which AWS account, region, project name and local CLI profile the `dev` environment uses |
| Related | [AWS_DEV_DEPLOYMENT_RUNBOOK.md](AWS_DEV_DEPLOYMENT_RUNBOOK.md), [QUICK_START.md](QUICK_START.md), [aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md](aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md) |

## 1. Summary

```text
Project name:     responsible-ai
Environment:      dev
Resource prefix:  responsible-ai-dev
AWS account:      767141477889
Region:           ap-southeast-1
State bucket:     responsible-ai-terraform-state-dev-767141477889   (S3)
Lock table:       responsible-ai-terraform-locks-dev                (DynamoDB)
CLI profile:      not pinned by the repo; any profile that resolves to 767141477889
```

## 2. Where the project name comes from

The project name is declared in two places and must stay in sync:

| File | Setting |
|---|---|
| `infra/live/dev/terragrunt.hcl` | `project_name = "responsible-ai"`, `environment = "dev"`, `resource_prefix = "${project_name}-${environment}"` |
| `deploy.sh` | `PROJECT_NAME="responsible-ai"` |

Every Terraform module derives its resource names from the prefix (`responsible-ai-dev-ai-gateway`,
`responsible-ai-dev-litellm-proxy`, `responsible-ai-dev-frontend-<account>`, the Cognito domain
`responsible-ai-dev-767141477889`, and so on). The state bucket and lock table names are also derived
from `project_name`, `environment` and `aws_account_id` in the root `terragrunt.hcl`.

## 3. Which AWS profile to use

The repository does not hardcode a named profile. The runbook and quick start both expect:

```bash
export AWS_PROFILE=<profile-that-resolves-to-767141477889>
export AWS_REGION=ap-southeast-1
aws sts get-caller-identity --query Account --output text   # must print 767141477889
```

On the primary development workstation (verified 2026-10-03):

| Profile | Credential type | Resolves to account | Notes |
|---|---|---|---|
| `default` | IAM access key | 767141477889 | Used when `AWS_PROFILE` is not set |
| `AiGateway` | IAM access key | 767141477889 | Same account; use when you want the intent to be explicit |

Both profiles are defined in `~/.aws/credentials` with `output = json` in `~/.aws/config` and no
region, so `AWS_REGION=ap-southeast-1` must be exported (or passed with `--region`).

The AWS MCP server used by Claude Code in this workspace is signed in to the same account as the IAM
user `bob-local`.

This page names profiles and an IAM user and nothing more. Access keys, session tokens and any other
credential value never go into this repository ([NO_SECRETS_IN_GIT.md](NO_SECRETS_IN_GIT.md)).

Profiles are machine-local. On a new machine, create any profile for account 767141477889 (IAM access
key or SSO) and run the identity check above before touching Terragrunt.

## 4. Why the identity check matters

Terragrunt derives the state bucket name from `aws_account_id` in `infra/live/dev/terragrunt.hcl`.
If the active credentials reach a different account, `backend bootstrap` will create a second state
bucket and a second stack there instead of failing. The earlier dev environment in account
`311464491957` is unrelated to the current one and is not managed by the live configuration.

## 5. Changing the target account

If dev ever moves to another account:

1. Update `aws_account_id` in `infra/live/dev/terragrunt.hcl`.
2. Update `domain_prefix` in `infra/live/dev/cognito/terragrunt.hcl` (Cognito domain prefixes are global).
3. Re-run `terragrunt backend bootstrap` from `infra/live/dev/network` with credentials for the new account.
4. Follow the runbook from section 3 onward and record a new snapshot under `docs/aws-snapshots/`.
