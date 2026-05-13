# Responsible AI EnterpriseReady Architecture Blueprint

## Executive Summary

This project turns the original Responsible AI Chat Agent prototype into an enterprise-oriented AI Gateway. The gateway preserves the natural synchronous chat flow while enforcing responsible-AI policy around the request and response pipe.

The first enterprise iteration intentionally avoids Kafka, SNS, SQS, Lambda brokers, and async chat workflows. The user experience remains:

```text
Chat client -> AI Gateway -> Groq -> AI Gateway -> Chat client
```

The backend is therefore an inline policy enforcement proxy, not a broker.

## Existing Single-Node Prototype Grade Architecture

The original project was optimized for local demonstration and responsible-AI feature exploration.

```text
React dev server
  -> FastAPI single process
  -> SQLite local file
  -> Groq API
  -> local Jaeger all-in-one
```

### Prototype Characteristics

| Area | Existing Shape | Scaling Concern |
|---|---|---|
| Frontend | Vite dev server | Not production hosting |
| Backend | Single Uvicorn process | Limited concurrency and resiliency |
| LLM call | Blocking HTTP call | Can tie up workers under load |
| Database | SQLite local file | Write bottleneck, not horizontally scalable |
| Identity | No real user login | Audits cannot be reliably mapped to users |
| Audit | Global audit records | Weak user/accountability model |
| Policy reports | Mostly request-local metadata | Limited enterprise reporting |
| Deployment | Docker Compose local workflow | No cloud autoscaling or managed resiliency |
| Observability | Local Jaeger | Not production retention or alerting |

This architecture is useful for development, demos, and responsible-AI experimentation. It is not suitable as-is for hundreds of concurrent enterprise users.

## Target V1 Enterprise Architecture

The target architecture keeps chat synchronous and introduces responsible-AI controls as an inline wrapper.

```text
User Browser
  -> CloudFront default HTTPS domain
  -> S3 private React frontend

React frontend
  -> API Gateway HTTP API default HTTPS endpoint
  -> AI Gateway on ECS Fargate
  -> Groq API
  -> AI Gateway
  -> React frontend

AI Gateway
  -> Cognito JWT validation
  -> Aurora PostgreSQL
  -> Secrets Manager / Parameter Store
  -> CloudWatch / X-Ray / OpenTelemetry
```

No ACM or Route53 are included in v1. The frontend uses the default CloudFront HTTPS domain and the backend uses the default API Gateway HTTPS domain.

## Core Request Flow

```text
1. User opens the CloudFront default HTTPS URL.
2. CloudFront serves the React app from a private S3 bucket.
3. User signs in or registers with Cognito.
4. React app sends a chat request with a Cognito JWT.
5. API Gateway forwards the request to the ECS-hosted AI Gateway.
6. AI Gateway validates the JWT and resolves user identity.
7. AI Gateway runs input privacy and safety checks.
8. AI Gateway redacts or blocks input when policy requires it.
9. AI Gateway calls Groq synchronously.
10. AI Gateway runs output responsible-AI checks.
11. AI Gateway writes user-scoped audit and violation records to Aurora.
12. AI Gateway returns the final answer synchronously to the client.
```

## Why AI Gateway, Not Broker

A broker changes the chat flow into a job workflow:

```text
Client -> Queue -> Worker -> Groq -> Database -> Polling/WebSocket -> Client
```

That pattern is appropriate for long-running jobs, batch evaluation, offline governance, or report generation. It is not the right first iteration for interactive chat because it adds latency, state management, and UX complexity.

The AI Gateway pattern keeps the pipe intact:

```text
Client -> Gateway -> Provider -> Gateway -> Client
```

Responsible AI wraps the pipe by enforcing input and output policies without changing the conversational contract.

## Scalability Model

The Groq call remains synchronous because users expect immediate chat responses. Scalability comes from:

- FastAPI running behind ECS Fargate service autoscaling.
- Async outbound Groq calls with connection pooling.
- Per-user and per-client rate limiting in a later hardening phase.
- Aurora PostgreSQL instead of SQLite.
- Minimal hot-path database writes.
- CloudWatch alarms and X-Ray/OpenTelemetry traces.
- Horizontal scaling of ECS tasks based on CPU, memory, and request count.

The external LLM provider quota remains the real upper bound. AWS can scale the gateway, but Groq rate limits and account quotas must be sized for the expected concurrency.

## First Iteration Deferred Items

The following are intentionally deferred:

- Kafka
- SNS/SQS fanout
- Background worker service
- Async chat response workflow
- WebSocket/polling response retrieval
- Custom domain, ACM, Route53
- Multi-region active-active
- Full Terraform module implementation

These can be added later once the synchronous gateway is production-stable.
