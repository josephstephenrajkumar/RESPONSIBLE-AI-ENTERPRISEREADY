# Service Deployment Guide

How to ship a new backend image, a new frontend build, or a LiteLLM configuration change to an environment whose
infrastructure already exists. Names below are the `dev` names; see the
[runbook](./AWS_DEV_DEPLOYMENT_RUNBOOK.md) for the full flow.

## Backend (AI Gateway)

```bash
SHA=$(git rev-parse --short HEAD)
ECR_URL=$(cd infra/live/dev/ecr && terragrunt output -raw repository_url)

docker build --platform linux/amd64 -t "responsible-ai-gateway:${SHA}" ./backend
aws ecr get-login-password --region ap-southeast-1 | docker login --username AWS --password-stdin "${ECR_URL%%/*}"
docker tag "responsible-ai-gateway:${SHA}" "${ECR_URL}:${SHA}"
docker push "${ECR_URL}:${SHA}"
```

Pin the tag and roll the service through Terraform (preferred: the task definition stays in state):

```bash
sed -i '' "s/image_tag *= *\"[^\"]*\"/image_tag          = \"${SHA}\"/" infra/live/dev/ecs-ai-gateway/terragrunt.hcl
(cd infra/live/dev/ecs-ai-gateway && terragrunt --non-interactive plan -out=/tmp/gw.tfplan && terragrunt --non-interactive apply /tmp/gw.tfplan)
git add infra/live/dev/ecs-ai-gateway/terragrunt.hcl && git commit -m "deploy: gateway image ${SHA}"
```

Monitor:

```bash
aws ecs describe-services --cluster responsible-ai-dev-cluster --services responsible-ai-dev-ai-gateway \
  --query 'services[0].deployments[].{state:rolloutState,taskdef:taskDefinition,running:runningCount}'
aws logs tail /ecs/responsible-ai-dev-ai-gateway --follow
```

## LiteLLM proxy configuration

Edit `litellm/config.yaml` (models, groups, fallbacks, budgets). Only list models the provider account serves.

```bash
(cd infra/live/dev/ecs-litellm-proxy && terragrunt --non-interactive plan -out=/tmp/llm.tfplan && terragrunt --non-interactive apply /tmp/llm.tfplan)   # re-uploads the S3 object
aws ecs update-service --cluster responsible-ai-dev-litellm-cluster --service responsible-ai-dev-litellm-proxy --force-new-deployment
aws logs tail /ecs/responsible-ai-dev-litellm-proxy --since 5m | grep -E "Proxy initialized|ERROR"
```

Rotating the provider key: `aws secretsmanager put-secret-value --secret-id responsible-ai-dev/groq_api_key ...`, then force a
new deployment of the proxy service. The gateway does not need to restart.

## Frontend

```bash
API=$(cd infra/live/dev/api-gateway && terragrunt output -raw api_endpoint)
BUCKET=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw bucket_name)
DIST=$(cd infra/live/dev/frontend-s3-cloudfront && terragrunt output -raw cloudfront_distribution_id)

echo "VITE_API_BASE=${API}" > frontend/.env.production
(cd frontend && npm ci && npm run build)
aws s3 sync frontend/dist/ "s3://${BUCKET}/" --delete --cache-control "public, max-age=31536000, immutable" --exclude index.html
aws s3 cp frontend/dist/index.html "s3://${BUCKET}/index.html" --cache-control "no-cache, no-store, must-revalidate"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*"
```

## Verify

```bash
curl -s "$API/health"
curl -s -o /dev/null -w '%{http_code}\n' "$API/gateway/health"          # 401 without a token
# with a Cognito id token:
curl -s -H "Authorization: Bearer $TOKEN" "$API/gateway/health"          # application_holds_provider_key: false
backend/venv/bin/python tests/run_scenarios.py --base-url "$API" --token "$TOKEN" --only LITELLM
```

## Rollback

Backend: set `image_tag` back to the previous sha and apply `ecs-ai-gateway` (or
`aws ecs update-service ... --task-definition responsible-ai-dev-ai-gateway:<previous revision>` for an immediate
revert, then reconcile Terraform). LiteLLM config: revert `litellm/config.yaml`, apply, force a new deployment.
Frontend: redeploy the previous build, or restore the previous object versions in the bucket.
