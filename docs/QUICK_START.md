# Quick Start Guide

The authoritative step-by-step flow is [AWS_DEV_DEPLOYMENT_RUNBOOK.md](./AWS_DEV_DEPLOYMENT_RUNBOOK.md). This page is the
short version. The current dev environment (URLs, ids) is in
[aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md](./aws-snapshots/2026-10-02-dev-deployment-snapshot-767141477889.md).

## Local (5 minutes)

```bash
git clone https://github.com/josephstephenrajkumar/RESPONSIBLE-AI-ENTERPRISEREADY.git
cd RESPONSIBLE-AI-ENTERPRISEREADY
cp backend/.env.example backend/.env           # set GROQ_API_KEY (used by the LiteLLM container)
docker compose up -d                           # Jaeger, Postgres, LiteLLM proxy
(cd backend && pip install -r requirements.txt && uvicorn app.main:app --port 8000 --reload) &
(cd frontend && npm install && npm run dev)
```

Open http://localhost:5173. Zero-spend alternative: `tests/mock_llm_upstream.py` + `docker-compose.mock.yml` (root README).

## AWS dev (about 45 minutes, mostly waiting on Aurora, CloudFront and image push)

```bash
export AWS_PROFILE=<profile-for-767141477889> AWS_REGION=ap-southeast-1
aws sts get-caller-identity --query Account --output text      # must print 767141477889

# once per account
(cd infra/live/dev/network && terragrunt --non-interactive backend bootstrap)

# plan -> review -> apply, in order
for m in network secrets cognito aurora-postgres ecr; do
  (cd infra/live/dev/$m && terragrunt --non-interactive plan -out=/tmp/$m.tfplan && terragrunt --non-interactive apply /tmp/$m.tfplan)
done
# store the Groq key and the gateway's LiteLLM key (runbook §7.2), create an admin user (§7.3)

# image
SHA=$(git rev-parse --short HEAD); ECR_URL=$(cd infra/live/dev/ecr && terragrunt output -raw repository_url)
docker build --platform linux/amd64 -t "responsible-ai-gateway:${SHA}" ./backend
aws ecr get-login-password | docker login --username AWS --password-stdin "${ECR_URL%%/*}"
docker tag "responsible-ai-gateway:${SHA}" "${ECR_URL}:${SHA}" && docker push "${ECR_URL}:${SHA}"
sed -i '' "s/image_tag *= *\"[^\"]*\"/image_tag          = \"${SHA}\"/" infra/live/dev/ecs-ai-gateway/terragrunt.hcl

for m in ecs-litellm-proxy ecs-ai-gateway api-gateway frontend-s3-cloudfront observability; do
  (cd infra/live/dev/$m && terragrunt --non-interactive plan -out=/tmp/$m.tfplan && terragrunt --non-interactive apply /tmp/$m.tfplan)
done
# build/upload the frontend and run the CloudFront second pass (runbook §12–13)
```

## Verify

```bash
API=$(cd infra/live/dev/api-gateway && terragrunt output -raw api_endpoint)
curl -s "$API/health"
# with a Cognito id token (runbook §15):
curl -s -H "Authorization: Bearer $TOKEN" "$API/gateway/health"    # expect application_holds_provider_key: false
```

## Cleanup

Runbook §17 (reverse order; `ecs-litellm-proxy` is destroyed after `ecs-ai-gateway`).
