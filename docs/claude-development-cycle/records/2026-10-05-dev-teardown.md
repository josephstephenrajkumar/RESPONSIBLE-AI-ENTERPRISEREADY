# Deploy Record — Dev environment teardown (account 767141477889)

Date: 2026-10-05
Requested by: repo owner (chat request, 5 October 2026: "tear down the AWS deployment")
Stage: DEPLOY (destructive); the request itself was the human gate.

```text
Scope:
  Everything under infra/live/dev in account 767141477889, region ap-southeast-1, resource prefix
  responsible-ai-dev. Out of scope: the Terraform state bucket and lock table, the unrelated cloudbox2
  workload in the same account, local code and docs other than the records below.

Pre-checks:
  - Identity: MCP session and the local Terragrunt credentials both resolve to 767141477889
    (network state returned vpc-0f6b4c53dd9d38e19, matching the snapshot).
  - Live inventory taken before the first destroy (4 ECS clusters incl. one foreign, 1 Aurora cluster,
    3 project buckets, 1 CloudFront distribution, 1 HTTP API, 1 user pool, 11 secrets, 1 ECR repo with
    12 images, 3 ALBs, 3 Container Insights log groups).
  - Data-retention settings read from the modules: Aurora skip_final_snapshot = true; frontend bucket
    without force_destroy; ECR without force_delete; secrets recovery_window_in_days = 7.
  - Manual Aurora cluster snapshot responsible-ai-dev-aurora-final-2026-10-05 created and confirmed
    available before the database step.

Execution (saved-plan flow; a bare `terragrunt destroy` is a blind apply and was refused by the session
policy, the reviewed `plan -destroy` → `apply <plan>` flow was allowed):
  observability 2 → frontend-s3-cloudfront 6 (bucket emptied first: 11 versions) → api-gateway 6
  → ecs-ai-gateway 16 → cognito 8 | ecs-litellm-proxy 22 | ecs-activepieces 17 | ecr 2 (12 images deleted
  first) → aurora-postgres 5 → secrets 26 → network 19.  Total 129 resources, every apply exit 0.
  api-gateway-workflows: state already empty, no changes; folder removed from the repo.
  Container Insights log groups (3) deleted by hand afterwards.

Verification:
  Account sweep by prefix after the last apply: no ECS cluster, RDS cluster, load balancer, security
  group, IAM role, alarm, log group, HTTP API, Cognito pool, CloudFront distribution, ECR repository or
  project bucket other than the state bucket. VPC and NAT gateway gone. Two unassociated Elastic IPs in
  the account belong to other projects (one tagged cloudbox-portal, one untagged) and were left alone.

Left in place (intentional):
  - RDS manual snapshot responsible-ai-dev-aurora-final-2026-10-05 (about 1 GB; cents per month).
  - 11 secrets responsible-ai-dev/* pending deletion until 2026-10-12.
  - State bucket responsible-ai-terraform-state-dev-767141477889 and lock table
    responsible-ai-terraform-locks-dev (empty states).

Repo changes (uncommitted, for review):
  - infra/live/dev/api-gateway-workflows removed.
  - docs/aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md: teardown addendum.
  - docs/AWS_DEV_DEPLOYMENT_RUNBOOK.md §17 rewritten (saved-plan destroy, full order, manual steps);
    §16 note on the legacy API updated.
  - docs/TECH_DEBT.md TD-30 resolved; docs/ROADMAP.md, docs/ACTIVEPIECES_INTEGRATION.md,
    docs/QUICK_START.md, docs/INFRASTRUCTURE_DEPLOYMENT.md, README.md, docs/TEST_PLAN.md,
    tests/README.md: pending-destroy wording and the dead API URL replaced.

Follow-ups for the owner:
  - Delete the manual snapshot when the dev data is no longer needed.
  - To redeploy: runbook from §3; enter the secret values again (Groq key, Activepieces keys).
```
