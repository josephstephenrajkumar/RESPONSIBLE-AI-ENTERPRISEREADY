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

## 2. AWS Login

Use any profile that resolves to the target account (IAM access key or SSO):

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

Use **Configuration → Model Catalogue** in the app (role `admin` or `model-admin`): pick an enabled provider,
choose a model from the discovered list (Bedrock shows what is invokable in the region), add it, then **Test** it.
Models added this way are stored in the proxy database (`store_model_in_db: true`) and survive restarts. To enable
Anthropic, OpenAI, Gemini or Mistral, store the key in Secrets Manager, mount it into the proxy
(`provider_secret_arns`) and add the provider to the gateway's `enabled_providers`, then plan/apply both ECS
modules — see [MODEL_CATALOG.md](MODEL_CATALOG.md).

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

Reverse order; decide on a final Aurora snapshot first.

```bash
for m in observability frontend-s3-cloudfront api-gateway ecs-ai-gateway ecs-litellm-proxy ecr aurora-postgres cognito secrets network; do
  (cd "infra/live/dev/$m" && terragrunt --non-interactive destroy)
done
```

Empty the frontend and LiteLLM config buckets first if `destroy` reports they are not empty.
