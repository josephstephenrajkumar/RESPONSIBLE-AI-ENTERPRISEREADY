# Response Caching with ElastiCache (Redis)

LiteLLM can cache completions in Redis so repeated prompts are answered without a provider call (lower cost and
latency). Nothing is deployed for this yet: the Proxy Manager's *Cache* panel shows LiteLLM's cache settings
(`GET /cache/settings`) and `/cache/ping` answers "Cache not initialized". This page is the runbook for enabling it
(roadmap Sprint 5).

## 1. Provision Redis

Add an `elasticache-redis` Terraform module (ElastiCache **Serverless** for Valkey/Redis OSS is the lowest-touch option;
a small `cache.t4g.micro` replication group also works for dev):

- private subnets, encryption in transit (TLS) and at rest, AUTH token stored in Secrets Manager
  (`responsible-ai-dev/redis_auth_token`)
- security group ingress **6379 from the LiteLLM proxy service security group** only
- outputs: `redis_endpoint`, `redis_port`

Wire into `ecs-litellm-proxy`: env `REDIS_HOST`, `REDIS_PORT`, `REDIS_SSL=True`, secret `REDIS_PASSWORD` (execution role
needs `GetSecretValue` on it). The gateway does not talk to Redis.

## 2. Turn caching on — two ways

**A. Repository-managed (recommended for production):** pin it in `litellm/config.yaml` and redeploy the proxy.

```yaml
litellm_settings:
  cache: true
  cache_params:
    type: redis                      # or redis-cluster / redis-sentinel
    host: os.environ/REDIS_HOST
    port: os.environ/REDIS_PORT
    password: os.environ/REDIS_PASSWORD
    ssl: true
    ttl: 3600                        # seconds; tune per use case
    supported_call_types: ["acompletion", "completion"]   # cache chat only, not embeddings/transcriptions
    namespace: "responsible-ai-dev"  # keep environments apart on a shared cluster
```

**B. Runtime, from the Proxy Manager (when `cache_params` is *not* pinned in the file):** Routing & Settings → Cache →
set Redis type/host/port/password/TLS/TTL (`POST /cache/settings`), test (`POST /cache/settings/test`), then verify with
`/cache/ping`. LiteLLM stores these in its database (`store_model_in_db: true` is already on) and applies them without a
restart. Use this for dev experiments; promote to config.yaml for prod so the setting is reviewed in Git.

Either way the gateway needs no change: cache hits come back from the proxy like any response, with
`x-litellm-cache-hit: true` (the client already reads `x-litellm-*` headers; Sprint 5 adds `cache_hit` to usage metering
and a cache-hit rate tile on the FinOps dashboard).

## 3. Governance choices

- **What to cache:** chat completions only. Do not cache calls that carry per-user context you would not want served to
  another user; in multi-tenant mode use a per-tenant `namespace` or key prefix (see `MULTI_TENANCY_DESIGN.md`) so one
  tenant's answers can never be served to another.
- **TTL:** short (minutes–hours) for conversational traffic; longer for deterministic, policy-type prompts.
- **Semantic caching** (`type: redis-semantic`, embedding similarity) is a later option; it changes answers for
  near-identical prompts and needs a responsible-AI review before use.
- **Invalidation:** `POST /cache/flushall` (Proxy Manager) after a model or policy change that must not serve stale
  answers. Key-level delete is `POST /cache/delete`.

## 4. Verify and operate

- `GET /cache/ping` → `{"status":"healthy", ...}`; `GET /cache/redis/info` for server stats.
- Send the same prompt twice through `/chat`; the second response should show the cache-hit header and near-zero
  latency on the AIOps dashboard.
- Watch ElastiCache CPU/memory and evictions in CloudWatch; size up before evictions rise.
- Cost: ElastiCache Serverless bills per GB-hour and ECPU; a dev cache is typically a few dollars per day. Weigh against
  the provider spend it removes (FinOps tab shows cost per call).
