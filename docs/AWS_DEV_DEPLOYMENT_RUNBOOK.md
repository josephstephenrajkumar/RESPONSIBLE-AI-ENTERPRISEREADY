# AWS Dev Deployment Runbook

This runbook documents the full `dev` deployment flow for Responsible AI EnterpriseReady. The
current dev environment and its live URLs are inventoried in
[aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md](aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md).

```text
AWS account:  767141477889
AWS region:   ap-southeast-1
Environment:  dev
Project:      responsible-ai
Terragrunt:   1.x (terraform >= 1.5)
```

What gets deployed:

```text
CloudFront -> S3 (React)
React -> API Gateway HTTP API -> VPC link -> ECS Fargate AI Gateway (policy enforcement, metering)
                                                  -> ECS Fargate LiteLLM proxy (provider keys, routing, budgets)
                                                        -> Groq / Amazon Bedrock
Both services -> Aurora PostgreSQL, CloudWatch, X-Ray (ADOT sidecars)
```

The gateway task never receives a provider key. Only the LiteLLM proxy task holds `GROQ_API_KEY`.

## 1. Verify Local Tools

```bash
aws --version          # v2
terraform version      # >= 1.5
terragrunt --version   # 1.x
docker --version       # must be able to build linux/amd64 images (Docker Desktop, or Colima with Rosetta)
node --version && npm --version
```

Enable the repository git hooks once per clone. They block commits and pushes that contain secret values
([NO_SECRETS_IN_GIT.md](NO_SECRETS_IN_GIT.md)):

```bash
git config core.hooksPath .githooks
python3 scripts/check_no_secrets.py --all      # expect: secret scan: clean
```

## 2. AWS Login

Use any profile that resolves to the target account (IAM access key or SSO). The profiles known to work and
where the project name is defined are listed in [AWS_ACCOUNT_AND_PROFILE.md](AWS_ACCOUNT_AND_PROFILE.md):

```bash
export AWS_PROFILE=<your-profile>
export AWS_REGION=ap-southeast-1
export AWS_PAGER=""
aws sts get-caller-identity --query Account --output text
```

Expected: `767141477889`. Stop if the account differs — Terragrunt will otherwise try to bootstrap a new state bucket and a
second stack in whatever account the credentials reach. The earlier dev environment in account `311464491957`
is unrelated to this one and is not managed by the current live configuration.

## 3. Non-Secret Inputs

All non-secret inputs live in `infra/live/dev/*/terragrunt.hcl` and are committed. Account-specific values:

| Where | Value |
|---|---|
| `infra/live/dev/terragrunt.hcl` | `aws_account_id = "767141477889"` (derives the state bucket name) |
| `cognito/terragrunt.hcl` | `domain_prefix = "responsible-ai-dev-767141477889"` (Cognito domain prefixes are global); `callback_urls` / `logout_urls` include the CloudFront domain |
| `api-gateway/terragrunt.hcl` | `allowed_origins` includes the CloudFront domain |
| `ecs-ai-gateway/terragrunt.hcl` | `image_tag` (commit sha of the pushed image), `frontend_origins`, `llm_default_model`, `llm_judge_model`, `llm_allowed_models`, `finops_monthly_budget_usd` |
| `litellm/config.yaml` | the `model_list` the proxy serves; only list models the provider account actually offers |

Secrets never go in markdown, Terragrunt files or chat: `GROQ_API_KEY`, LiteLLM keys, database passwords, AWS credentials.

## 4. Deployment Order

```text
1. network
2. secrets            (then store the Groq key and the gateway's LiteLLM key)
3. cognito
4. aurora-postgres
5. ecr
6. build and push the backend image; pin image_tag
7. ecs-litellm-proxy
8. ecs-ai-gateway
9. api-gateway
10. frontend-s3-cloudfront; build and upload the frontend
11. second pass: CloudFront origin into cognito, api-gateway, ecs-ai-gateway
12. observability
```

## 5. Bootstrap Remote State (once per account)

Terragrunt 1.x does not create the state bucket during `plan`:

```bash
cd infra/live/dev/network
terragrunt --non-interactive backend bootstrap
cd -
```

Creates `responsible-ai-terraform-state-dev-767141477889` (S3) and `responsible-ai-terraform-locks-dev` (DynamoDB).

## 6. Plan, Review, Apply

Always apply a saved plan you have read:

```bash
mkdir -p /tmp/tfplans
cd infra/live/dev/<module>
terragrunt --non-interactive plan -out=/tmp/tfplans/<module>.tfplan
terragrunt --non-interactive show /tmp/tfplans/<module>.tfplan | grep -E "will be|Plan:"
terragrunt --non-interactive apply /tmp/tfplans/<module>.tfplan
cd -
```

`./deploy.sh plan <module>` is a convenient wrapper for planning; its `apply` uses `-auto-approve`, so prefer the
saved-plan flow above for anything beyond a fresh, additive module.

## 7. Foundation

### 7.1 Network

Plan/apply `network` (19 resources: VPC `10.0.0.0/16`, IGW, one NAT gateway, 2 public / 2 private / 2 database subnets).

### 7.2 Secrets

Plan/apply `secrets`. Created under `responsible-ai-dev/`:

```text
groq_api_key               placeholder  -> store the real key (below)
litellm_master_key         generated    (LiteLLM admin key; operators only)
litellm_gateway_key        placeholder  -> key the AI Gateway uses against the proxy (below)
database_master_password   generated
jwt_secret                 generated    (unused; TD-17)
```

Store the Groq key without echoing it (reads `backend/.env`):

```bash
aws secretsmanager put-secret-value --secret-id responsible-ai-dev/groq_api_key \
  --secret-string "$(grep -E '^GROQ_API_KEY=' backend/.env | cut -d= -f2-)"
```

Gateway key. In dev the gateway currently uses the master key (TD-25) because the proxy ALB is VPC-internal and
`/key/generate` cannot be called from a laptop before anything is deployed:

```bash
aws secretsmanager put-secret-value --secret-id responsible-ai-dev/litellm_gateway_key \
  --secret-string "$(aws secretsmanager get-secret-value --secret-id responsible-ai-dev/litellm_master_key --query SecretString --output text)"
```

Replace it with a scoped virtual key once the proxy is up (section 15).

### 7.3 Cognito

Plan/apply `cognito` (user pool, app client, hosted-UI domain, groups `admin`, `policy-manager`, `guardrails-admin`,
`finops`, `aiops`). `allow_admin_user_password_auth = true` in dev enables `ADMIN_USER_PASSWORD_AUTH` for scripted
smoke tests; leave it `false` elsewhere.

Create the first administrator (Cognito emails a temporary password):

```bash
POOL=$(cd infra/live/dev/cognito && terragrunt output -raw user_pool_id)
aws cognito-idp admin-create-user --user-pool-id "$POOL" --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --username you@example.com --group-name admin
```

`admin` sees every screen; `finops` / `aiops` see only their dashboard; `policy-manager` sees the responsible-AI screens.

### 7.4 Aurora PostgreSQL

Plan/apply `aurora-postgres` (Serverless v2, 0.5–2 ACU, ~6 minutes for the instance). One database `responsible_ai`
holds the application tables and LiteLLM's `LiteLLM_*` tables in dev; use a separate database/schema in prod (TD-13).

### 7.5 ECR

Plan/apply `ecr` (repository `responsible-ai-dev-ai-gateway`, scan on push).

## 8. Build And Push The Backend Image

Fargate runs `linux/amd64`; build for it explicitly and tag with the commit you are deploying:

```bash
SHA=$(git rev-parse --short HEAD)
ECR_URL=$(cd infra/live/dev/ecr && terragrunt output -raw repository_url)

docker build --platform linux/amd64 -t "responsible-ai-gateway:${SHA}" ./backend
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin "${ECR_URL%%/*}"
docker tag "responsible-ai-gateway:${SHA}" "${ECR_URL}:${SHA}"
docker tag "responsible-ai-gateway:${SHA}" "${ECR_URL}:latest"
docker push "${ECR_URL}:${SHA}"
docker push "${ECR_URL}:latest"
```

Then set `image_tag = "<SHA>"` in `infra/live/dev/ecs-ai-gateway/terragrunt.hcl` and commit it. (In zsh write
`"${ECR_URL}:latest"`, not `"$ECR_URL:latest"` — `:l` is a lowercase modifier.)

## 9. Deploy The LiteLLM Proxy

Plan/apply `ecs-litellm-proxy` (22 resources). Terraform uploads `litellm/config.yaml` to the private config
bucket; the task loads it at start-up (`LITELLM_CONFIG_BUCKET_*` plus the `--config` flag the module passes).

Verify:

```bash
cd infra/live/dev/ecs-litellm-proxy && terragrunt output -raw proxy_url && cd -
aws logs tail /ecs/responsible-ai-dev-litellm-proxy --since 10m | grep -E "Proxy initialized|prisma|ERROR"
```

Expect `prisma migrate deploy completed` and `LiteLLM: Proxy initialized with Config, Set models:`. If the bucket read
fails the task exits instead of starting with no models.

Changing models, fallbacks or budgets: edit `litellm/config.yaml`, plan/apply this module (re-uploads the object), then
`aws ecs update-service --cluster responsible-ai-dev-litellm-cluster --service responsible-ai-dev-litellm-proxy --force-new-deployment`.
Only list models the Groq account serves — check with `curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models`.

## 10. Deploy The AI Gateway

Plan/apply `ecs-ai-gateway` (16 resources on first deploy; a task-definition revision swap afterwards). Confirm the
credential boundary before applying:

```bash
cd infra/live/dev/ecs-ai-gateway
terragrunt --non-interactive show -json /tmp/tfplans/ecs-ai-gateway.tfplan \
  | python3 -c "import sys,json; p=json.load(sys.stdin); td=[r for r in p['resource_changes'] if r['type']=='aws_ecs_task_definition'][0]; c=[x for x in json.loads(td['change']['after']['container_definitions']) if x['name']=='ai-gateway'][0]; print(c['image']); print([s['name'] for s in c.get('secrets',[])])"
cd -
```

Expected secrets: `['LITELLM_API_KEY']` only. Wait for the service to stabilise, then check logs:

```bash
aws ecs describe-services --cluster responsible-ai-dev-cluster --services responsible-ai-dev-ai-gateway \
  --query 'services[0].deployments[0].rolloutState'
aws logs tail /ecs/responsible-ai-dev-ai-gateway --since 10m | grep -E "Application startup|ERROR|Traceback"
```

## 11. Deploy API Gateway

Plan/apply `api-gateway`, then:

```bash
API=$(cd infra/live/dev/api-gateway && terragrunt output -raw api_endpoint)
curl -s "$API/health"            # 200 {"status":"ok",...}
curl -s -o /dev/null -w '%{http_code}\n' "$API/gateway/health"   # 401 without a token (AUTH_REQUIRED=true)
```

## 12. Frontend Hosting, Build And Upload

Plan/apply `frontend-s3-cloudfront` (CloudFront takes a few minutes), then:

```bash
API=$(cd infra/live/dev/api-gateway && terragrunt output -raw api_endpoint)
BUCKET=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw bucket_name)
DIST=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw cloudfront_distribution_id)
CF=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw cloudfront_domain_name)

echo "VITE_API_BASE=${API}" > frontend/.env.production
(cd frontend && npm ci && npm run build)
aws s3 sync frontend/dist/ "s3://${BUCKET}/" --delete \
  --cache-control "public, max-age=31536000, immutable" --exclude index.html
aws s3 cp frontend/dist/index.html "s3://${BUCKET}/index.html" --cache-control "no-cache, no-store, must-revalidate"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*"
echo "https://${CF}"
```

Commit `frontend/.env.production`.

## 13. Second Pass: CloudFront Origin

Add `https://<CF>` (and `https://<CF>/` for Cognito) to:

- `infra/live/dev/cognito/terragrunt.hcl` — `callback_urls`, `logout_urls`
- `infra/live/dev/api-gateway/terragrunt.hcl` — `allowed_origins`
- `infra/live/dev/ecs-ai-gateway/terragrunt.hcl` — `frontend_origins`

Plan/apply all three (cognito and api-gateway are in-place updates; the gateway gets a new task-definition revision).
Verify the preflight:

```bash
curl -s -o /dev/null -D - -X OPTIONS "$API/chat" -H "Origin: https://${CF}" \
  -H "Access-Control-Request-Method: POST" -H "Access-Control-Request-Headers: authorization,content-type" \
  | grep -iE "^HTTP|access-control-allow-origin"
```

`HTTP/2 400` with body `Disallowed CORS origin` means API Gateway matched but the gateway task has not been redeployed
with the new `FRONTEND_ORIGINS` yet.

## 14. Observability

Plan/apply `observability` (gateway ECS CPU alarm, log error filter). The LiteLLM module adds ALB 5xx and unhealthy-host
alarms itself. Traces from both services arrive in X-Ray via the ADOT sidecars.

## 15. Verification And Operations

### Authenticated smoke test

Log in through the CloudFront site, or in dev obtain a token for a test user:

```bash
POOL=$(cd infra/live/dev/cognito && terragrunt output -raw user_pool_id)
CLIENT=$(cd infra/live/dev/cognito && terragrunt output -raw app_client_id)
TOKEN=$(aws cognito-idp admin-initiate-auth --user-pool-id "$POOL" --client-id "$CLIENT" \
  --auth-flow ADMIN_USER_PASSWORD_AUTH --auth-parameters USERNAME=<user>,PASSWORD=<password> \
  --query 'AuthenticationResult.IdToken' --output text)

curl -s -H "Authorization: Bearer $TOKEN" "$API/gateway/health" | python3 -m json.tool
backend/venv/bin/python tests/run_scenarios.py --base-url "$API" --token "$TOKEN" --only LITELLM
```

Expect `"mode": "proxy"`, `"reachable": true`, `"default_model_available": true`, `"application_holds_provider_key": false`.
Then open the FinOps and AIOps tabs: the smoke-test calls should be visible with `cost_source = litellm`.

### Issue a scoped LiteLLM key for the gateway (removes TD-25)

From inside the VPC (ECS Exec into the gateway task, or a one-off Fargate task):

```bash
curl -X POST "$PROXY_URL/key/generate" -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
  -d '{"key_alias":"ai-gateway-dev","team_id":"ai-gateway","max_budget":50,"budget_duration":"30d","models":["openai/gpt-oss-120b","openai/gpt-oss-20b","chat-default","judge-fast"]}'
```

Store the returned key in `responsible-ai-dev/litellm_gateway_key` and force a new deployment of the gateway service.

### Adding providers and models

Use the **Proxy Manager** tab in the app (role `admin` or `model-admin`). Providers: store a provider API key
(encrypted in the proxy database) or enable/disable a provider; Models: pick an enabled provider,
choose a model from the discovered list (Bedrock shows what is invokable in the region), add it, then **Test** it.
Models added this way are stored in the proxy database (`store_model_in_db: true`) and survive restarts. Teams,
virtual keys, MCP servers and proxy-side guardrails are managed from the same tab — see
[LITELLM_PROXY_MANAGER.md](LITELLM_PROXY_MANAGER.md) and [MODEL_CATALOG.md](MODEL_CATALOG.md).

### Rotate the Groq key

`put-secret-value` on `responsible-ai-dev/groq_api_key`, then force a new deployment of the **proxy** service only.

## 16. Common Issues

| Symptom | Cause / fix |
|---|---|
| `S3 bucket ... does not exist` during `plan` | Run `terragrunt backend bootstrap` once (section 5). |
| Proxy returns 401/404 from Groq for a model | The Groq account does not serve that model (e.g. `llama-3.x`). Use the account's model list; LiteLLM retries and falls back before surfacing the provider error. |
| Framework-mode answer says the model returned no text (`finish_reason=length`) | GPT-OSS spends tokens on hidden reasoning; raise `max_tokens` (the UI default is 800). |
| Bedrock Claude model returns `404 Model use case details have not been submitted` | One-time Anthropic use-case form in the Bedrock console (account level); Nova models work without it. See [MODEL_CATALOG.md](MODEL_CATALOG.md). |
| Preflight `400 Disallowed CORS origin` | Gateway task not yet redeployed with the CloudFront origin (section 13). |
| `repository ... does not exist` on `docker push :latest` | zsh parsed `$ECR_URL:latest` as `${ECR_URL:l}`; quote as `"${ECR_URL}:latest"`. |
| `Using terragrunt.hcl as the root ... anti-pattern` warning | Harmless with Terragrunt 1.1; rename to `root.hcl` when convenient. |
| Guardrails Hub validators missing in a fresh environment | Install them from Configuration → Guardrails Hub Validators, or move installs into the image build (TD-19). |
| Costs while idle | NAT gateway, Aurora minimum ACU, two Fargate services, two internal ALBs — roughly $170–200/month. Destroy when not needed. |

## 17. Destroy

Last run 2026-10-05: the whole dev environment (11 modules, 129 resources) came down this way in about half an hour; see
the last addendum of
[aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md](aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md).

Dependents first. This order respects every `dependency` block; the four modules in braces do not depend on each other
and can run in parallel:

```text
observability → frontend-s3-cloudfront → api-gateway → ecs-ai-gateway
→ { cognito, ecs-litellm-proxy, ecs-activepieces, ecr } → aurora-postgres → secrets → network
```

Use saved plans so every destroy is reviewed before it runs (the same flow as section 8). Terraform colours the word
"destroyed", so strip the escape codes before grepping.

```bash
export AWS_REGION=ap-southeast-1
PLANS=$(mktemp -d)
ORDER="observability frontend-s3-cloudfront api-gateway ecs-ai-gateway cognito ecs-litellm-proxy ecs-activepieces ecr aurora-postgres secrets network"
for m in $ORDER; do
  (cd "infra/live/dev/$m" && terragrunt --non-interactive plan -destroy -out="$PLANS/$m.tfplan") \
    | sed 's/\x1b\[[0-9;]*m//g' | grep -E "will be destroyed|Plan:"
done
```

Review the lists (every resource should carry the `responsible-ai-dev` prefix), then apply in order. Three steps need a hand
between applies:

1. **Database.** `aurora-postgres` sets `skip_final_snapshot = true` and the automated snapshots disappear with the cluster.
   If the data matters, create a manual cluster snapshot of `responsible-ai-dev-aurora` first and wait until it is
   `available` (a cluster cannot be deleted while a snapshot is being taken).
2. **Frontend bucket.** `responsible-ai-dev-frontend-<account>` has no `force_destroy`: delete every object version before
   applying `frontend-s3-cloudfront`. The LiteLLM config bucket has `force_destroy` and needs nothing.
3. **ECR images.** `responsible-ai-dev-ai-gateway` has no `force_delete`: delete its images after `ecs-ai-gateway` is gone
   and before applying `ecr`.

```bash
for m in $ORDER; do
  (cd "infra/live/dev/$m" && terragrunt --non-interactive apply "$PLANS/$m.tfplan")
done
```

Slow steps: CloudFront about 3 minutes, each ECS service drain 3 to 8 minutes, Aurora about 9 minutes, NAT gateway about
3 minutes.

Afterwards:

- Secrets Manager keeps the eleven `responsible-ai-dev/*` secrets for the 7-day recovery window
  (`recovery_window_in_days = 7`); a redeploy inside that window must restore them or the `secrets` apply fails on the names.
- ECS creates the Container Insights log groups `/aws/ecs/containerinsights/responsible-ai-dev-*/performance` outside
  Terraform; delete them by hand.
- The state bucket `responsible-ai-terraform-state-dev-<account>` and the lock table stay (empty states, cents per month)
  so a redeploy needs no new `backend bootstrap`.
- Sweep the account for anything left with the `responsible-ai` prefix: ECS clusters, RDS clusters and snapshots, load
  balancers, security groups, IAM roles, alarms, log groups, HTTP APIs, Cognito pools, CloudFront distributions, S3
  buckets, ECR repositories. The account also hosts unrelated workloads; touch nothing without the prefix.

## 16. Workflow Apps engine (Activepieces)

Added 2026-10-03 ([ACTIVEPIECES_INTEGRATION.md](ACTIVEPIECES_INTEGRATION.md)). Deploy order: `secrets` (new keys) →
`ecs-activepieces` → `ecs-ai-gateway` (new image with the piece archives and the `ACTIVEPIECES_*` settings) → frontend.
The portal's Workflow Studio and app chat reach the engine through the gateway only. The HTTP API
`api-gateway-workflows` of the first delivery is gone and its folder was removed from the repo on 2026-10-05; the engine has
no public endpoint.

1. Build the pieces once per change and stage them into the image context:
   `cd workflows/pieces && npm install && npm run build && cd ../.. && cp -R workflows/pieces/dist/. backend/pieces/`
   (`backend/pieces/` is gitignored; the Dockerfile copies it to `/app/pieces`).
2. Apply `secrets`, then set the three values out of band (never in files):
   `activepieces_encryption_key` = 32 hex characters, `activepieces_jwt_secret`, `activepieces_service_password`.
3. Plan and apply `ecs-activepieces` from a saved plan; wait for the target `responsible-ai-dev-ap` to be healthy
   (`/api/v1/flags`). The engine runs migrations on the shared Aurora database at first start.
4. Build, push and roll the gateway image as in section 8; the startup bootstrap creates the service account on a fresh
   engine (first sign-up = platform admin), installs the archives and configures the AI provider. Check
   `GET /workflows/status` (admin token): `signed_in`, `pieces` states and `last_bootstrap.errors == []`.
5. Verify end to end: `python3 tests/workflow_apps_e2e.py --base-url "$API" --token "$TOKEN" --cleanup` (templates,
   publish, chat, metering) and `python3 tests/workflow_studio_e2e.py --base-url "$API" --token "$TOKEN"` (a flow built
   step by step through the Studio API, step test, publish, chat, run detail, router/code/loop shapes).

Builders use the Workflow Studio in the portal; the engine's service account is used by the gateway only (TD-31). There is
no public chat page: app chat is `POST /workflows/apps/{id}/chat` under Cognito or an app token (TD-30 closed).

AWS pieces (2026-10-05): the engine task role carries the Bedrock, OpenSearch and Quick permissions
(`aws_pieces_enabled`, `assumable_role_arns` in the `ecs-activepieces` module) and the task sets
`AP_SANDBOX_PROPAGATED_ENV_VARS` so piece execution can reach the task-role credentials; a change to either replaces the
engine task (in-memory queue: in-flight runs are lost). The gateway task gets `PUBLIC_BASE_URL` (the HTTP API endpoint)
for MCP metadata; `tests/mcp_e2e.py --base-url "$API" --token "$TOKEN"` verifies the MCP endpoint
([MCP_PUBLISHING.md](MCP_PUBLISHING.md)).
