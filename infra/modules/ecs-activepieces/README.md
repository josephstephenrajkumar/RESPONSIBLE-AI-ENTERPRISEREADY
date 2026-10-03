# ecs-activepieces

Activepieces 0.92 (community edition) on ECS Fargate behind an internal ALB, for the Workflow Apps feature
(see `docs/ACTIVEPIECES_INTEGRATION.md`). One task runs API and worker. The engine has no public URL: the
gateway is its only client (Workflow Studio and app chat go through the gateway), and the engine's worker
fetches piece bundles from the same internal ALB (`AP_FRONTEND_URL`).

Inputs of note: `postgres_*` (Aurora, SSL enforced; the RDS CA bundle for ap-southeast-1 ships in this folder),
`encryption_key_secret_arn` (32 hex characters), `jwt_secret_secret_arn`.
`desired_count` must stay 1 while the queue is in-memory (`AP_REDIS_TYPE=MEMORY`).
