# ecs-activepieces

Activepieces 0.92 (community edition) on ECS Fargate behind an internal ALB, for the Workflow Apps feature
(see `docs/ACTIVEPIECES_INTEGRATION.md`). One task runs API, worker and UI. Browsers reach it through the
HTTP API created by `infra/live/dev/api-gateway-workflows`; the gateway and the engine's worker use the internal ALB.

Inputs of note: `postgres_*` (Aurora, SSL enforced; the RDS CA bundle for ap-southeast-1 ships in this folder),
`encryption_key_secret_arn` (32 hex characters), `jwt_secret_secret_arn`, `allowed_embed_origins` (CloudFront domain).
`desired_count` must stay 1 while the queue is in-memory (`AP_REDIS_TYPE=MEMORY`).
