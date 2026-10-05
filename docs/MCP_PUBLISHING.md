# MCP publishing: workflow apps as tools for external agents

| | |
|---|---|
| Status | Delivered 2026-10-05 (Sprint AQ-2 in [ROADMAP.md](ROADMAP.md)); dev AWS verification recorded in [ACTIVEPIECES_INTEGRATION.md](ACTIVEPIECES_INTEGRATION.md) §10b |
| Code | `backend/app/mcp_server.py`, `frontend/src/components/McpPanel.jsx`, tests `backend/tests/test_mcp_server.py`, `tests/mcp_e2e.py` |

## 1. What it does

A workflow app that an administrator marks **Publish as tool** becomes a tool of the gateway's MCP server. External
agents that speak the Model Context Protocol (Amazon Quick Suite chat agents and flows through an *Actions → MCP*
integration, Claude Code and Claude Desktop, LiteLLM's MCP gateway, IDE agents) list the tool, read its description and
call it with a `message`. The call runs the app's **published** flow exactly like the Chat tab or
`POST /workflows/apps/{id}/chat`: the Responsible AI pipeline, the app's LiteLLM key and budget, FinOps metering and the
run history all apply unchanged. The engine stays internal; only the gateway endpoint is reachable.

The reverse direction (our workflows calling AWS) is the set of AWS pieces in `workflows/pieces/aws-*`
([ACTIVEPIECES_INTEGRATION.md](ACTIVEPIECES_INTEGRATION.md) §5.6).

## 2. Publishing an app

Workflow Apps screen → **MCP server** section:

1. **Publish as tool** on an app. The tool name defaults to a slug of the app name (lowercase, digits, underscores) and
   the description to the app description; **Edit** changes both. Names are unique per tenant. A tool is visible to
   clients only while the app itself is published; disabling the app hides it, deleting the app removes it.
2. **Issue key**: an MCP key (`rai_mcp_…`) is shown once and stored as a SHA-256 hash. Keys belong to the tenant of
   the administrator who issued them and can be revoked at any time.
3. The same controls exist in the Studio header (**MCP: on/off**).

## 3. Endpoint and protocol

- Endpoint: `POST {PUBLIC_BASE_URL}/mcp` (dev: the HTTP API endpoint of the gateway), streamable-HTTP transport with
  plain JSON responses (no server-initiated streams: `GET /mcp` answers 405, `DELETE /mcp` 204). The server is
  stateless; no `Mcp-Session-Id` is issued.
- Methods: `initialize` (protocol versions 2025-06-18, 2025-03-26, 2024-11-05 negotiated), `notifications/initialized`
  (202), `ping`, `tools/list`, `tools/call`, and empty `resources/list`, `resources/templates/list`, `prompts/list`.
- Tool input schema: `{ "message": string (required), "session_id": string (optional) }`. Every call without a
  `session_id` starts a fresh conversation; the id returned in `structuredContent.session_id` can be sent back on the
  next turn of the same user. Users behind one shared key never share memory by accident.
- Result: `content: [{type: "text", text}]` (markdown), `structuredContent: {answer, session_id, app_id, latency_ms}`,
  `isError` for unknown tools, missing message, engine or app failures.
- Limits: request body 256 KB, batch of at most 10 messages, API Gateway integration timeout 30 s (a tool call that
  runs longer returns 504 at the edge while the flow still completes; TD-38).

## 4. Authentication

| Credential | Use |
|---|---|
| MCP key `rai_mcp_…` (bearer) | The normal path for integrations (Quick Suite, LiteLLM, Claude). Tenant-scoped. |
| Cognito ID token (bearer) | Interactive clients that can sign in as a portal user. |
| OAuth discovery | `401` responses carry `WWW-Authenticate: Bearer resource_metadata="…/.well-known/oauth-protected-resource"`; that document names the Cognito issuer. Cognito has no dynamic client registration, so OAuth-only clients need a pre-registered app client (TD-36). |
| Workflow app tokens `rai_app_…` | Rejected (403): an app must not call back into the MCP server. |

Every `tools/call` is recorded as an admin event (`mcp_tool_call`: key or subject, tool, app, latency, error flag), in
addition to the app's own run and metering records.

## 5. Connecting clients

**Amazon Quick Suite** (Enterprise subscription): *Integrations → Actions → Model Context Protocol*, endpoint
`{PUBLIC_BASE_URL}/mcp`, remote transport (streamable HTTP), authentication: bearer with the MCP key. Quick registers
the tool list on connection; after publishing new tools, re-establish the integration so Quick refreshes the list.
Each tool then appears as an action for Quick chat agents and Quick Flows.

**Claude Code**: `claude mcp add --transport http responsible-ai {PUBLIC_BASE_URL}/mcp --header "Authorization: Bearer <key>"`.

**LiteLLM proxy**: Proxy Manager → MCP servers → URL `{PUBLIC_BASE_URL}/mcp`, transport http, auth bearer, the key.
Models behind the proxy can then call the apps as tools.

**Any client**: JSON-RPC over HTTP as in section 3; `tests/mcp_e2e.py` is a reference client.

## 6. Security model

- A key or token resolves to one tenant; `tools/list` and `tools/call` see only that tenant's published tools, and the
  tool row must belong to the same tenant as the app (checked on every call).
- The flow runs under the app's own credentials (its gateway app token and LiteLLM key); the MCP caller never receives
  them. Budgets stop the app when exhausted, independent of the caller.
- Keys are shown once, hashed at rest, revocable; `last_used_at` is kept (written at most once a minute).
- The endpoint is public HTTPS behind API Gateway with default-route throttling (burst 100, 50 requests/s); the
  gateway rejects oversized bodies and batches.
- What a tool can do is exactly what the app's flow does. Review a flow before publishing it as a tool; a tool that
  writes to Salesforce, Slack or a calendar acts with the connections stored in that app.

## 7. Known limits

- OAuth-only MCP clients: no dynamic client registration on Cognito (TD-36).
- 30 s edge timeout for long-running tools (TD-38).
- One engine project for all tenants (TD-31): tenancy is enforced by the gateway registry, not inside the engine.
