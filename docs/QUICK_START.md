# Quick Start Guide

## 5-Minute Setup

```bash
# 1. Clone and navigate
git clone https://github.com/josephstephenrajkumar/RESPONSIBLE-AI-ENTERPRISEREADY.git
cd RESPONSIBLE-AI-ENTERPRISEREADY

# 2. Configure AWS
aws configure

# 3. Verify access
aws sts get-caller-identity
```

## Deploy Infrastructure (20 minutes)

```bash
chmod +x deploy.sh

# Initialize backends
./deploy.sh init

# Plan changes
./deploy.sh plan

# Apply infrastructure
./deploy.sh apply
```

## Deploy Services (10 minutes)

### Backend

```bash
cd backend
docker build -t responsible-ai-gateway:latest .

ECR_URL=$(aws ecr describe-repositories \
  --repository-names responsible-ai-gateway \
  --query 'repositories[0].repositoryUri' \
  --output text)

aws ecr get-login-password --region ap-southeast-1 | \
  docker login --username AWS --password-stdin $(echo $ECR_URL | cut -d/ -f1)

docker tag responsible-ai-gateway:latest ${ECR_URL}:latest
docker push ${ECR_URL}:latest

aws ecs update-service --cluster responsible-ai-dev \
  --service responsible-ai-gateway --force-new-deployment

cd ..
```

### Frontend

```bash
cd frontend
npm install
npm run build

S3_BUCKET=$(aws s3 ls \
  --query "Buckets[?contains(Name, 'responsible-ai-frontend-dev')].Name" \
  --output text)

aws s3 sync dist/ s3://${S3_BUCKET}/ --delete

DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[0].Id" \
  --output text)

aws cloudfront create-invalidation --distribution-id ${DIST_ID} --paths "/*"

cd ..
```

## Access Your Deployment

```bash
# Backend health check
API_ENDPOINT=$(aws apigatewayv2 get-apis \
  --query "Items[?Name=='responsible-ai-api'].ApiEndpoint" \
  --output text)
curl ${API_ENDPOINT}/health

# Frontend URL
CF_DOMAIN=$(aws cloudfront get-distribution \
  --id ${DIST_ID} \
  --query 'Distribution.DomainName' \
  --output text)
echo "https://${CF_DOMAIN}"
```

## Cleanup

```bash
./deploy.sh destroy --auto-approve
```

See detailed guides:
- [INFRASTRUCTURE_DEPLOYMENT.md](./INFRASTRUCTURE_DEPLOYMENT.md)
- [SERVICE_DEPLOYMENT.md](./SERVICE_DEPLOYMENT.md)
- [ARCHITECTURE_BLUEPRINT.md](./ARCHITECTURE_BLUEPRINT.md)
