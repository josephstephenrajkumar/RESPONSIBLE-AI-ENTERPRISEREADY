# Service Deployment Guide

## Backend Service Deployment

### Build Docker Image

```bash
cd backend

# Build image
docker build -t responsible-ai-gateway:latest .

cd ..
```

### Push to ECR

```bash
# Get ECR repository URL
ECR_URL=$(aws ecr describe-repositories \
  --repository-names responsible-ai-gateway \
  --query 'repositories[0].repositoryUri' \
  --output text)

# Login to ECR
aws ecr get-login-password --region ap-southeast-1 | \
  docker login --username AWS --password-stdin $(echo $ECR_URL | cut -d/ -f1)

# Tag and push
docker tag responsible-ai-gateway:latest ${ECR_URL}:latest
docker push ${ECR_URL}:latest
```

### Deploy to ECS

```bash
# Update service to use new image
aws ecs update-service \
  --cluster responsible-ai-dev \
  --service responsible-ai-gateway \
  --force-new-deployment

# Monitor deployment
aws logs tail /ecs/responsible-ai-gateway-dev --follow
```

## Frontend Service Deployment

### Build React App

```bash
cd frontend

npm install
npm run build

cd ..
```

### Upload to S3

```bash
# Get S3 bucket name
S3_BUCKET=$(aws s3 ls \
  --query "Buckets[?contains(Name, 'responsible-ai-frontend-dev')].Name" \
  --output text)

# Upload files
aws s3 sync frontend/dist/ s3://${S3_BUCKET}/ --delete
```

### Invalidate CloudFront Cache

```bash
# Get distribution ID
DIST_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[0].Id" \
  --output text)

# Clear cache
aws cloudfront create-invalidation --distribution-id ${DIST_ID} --paths "/*"
```

## Verify Services

```bash
# Get API endpoint
API_ENDPOINT=$(aws apigatewayv2 get-apis \
  --query "Items[?Name=='responsible-ai-api'].ApiEndpoint" \
  --output text)

# Test health
curl -X GET "${API_ENDPOINT}/health"

# Get CloudFront domain
CF_DOMAIN=$(aws cloudfront get-distribution \
  --id ${DIST_ID} \
  --query 'Distribution.DomainName' \
  --output text)

echo "Frontend: https://${CF_DOMAIN}"
```

## Rollback

```bash
# Rollback backend to previous task definition
aws ecs update-service \
  --cluster responsible-ai-dev \
  --service responsible-ai-gateway \
  --task-definition responsible-ai-gateway:1 \
  --force-new-deployment

# Rollback frontend (restore previous S3 version)
# Use S3 version history to restore
```
