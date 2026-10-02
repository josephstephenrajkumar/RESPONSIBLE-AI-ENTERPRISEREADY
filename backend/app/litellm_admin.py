"""Governed access to the LiteLLM proxy's management API for the Proxy Manager screen.

The frontend never talks to LiteLLM directly (the proxy is VPC-internal and its admin
key must not reach a browser). Instead the gateway exposes one route,

    ANY /gateway/admin/litellm/{path}

which forwards only allow-listed management paths, swaps in the proxy admin key,
records every mutating call in the policy audit trail with secrets redacted, and
returns LiteLLM's response as-is. Curated endpoints build on the same client.
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import httpx

from app.config import Settings
from app.database import PolicyAuditEvent, SessionLocal

# (methods, path regex). Inference routes are deliberately absent: model calls
# go through app.llm_client so they are metered and policy-checked.
ALLOWED_ROUTES = [
    ({'GET'}, r'^/health(/readiness|/liveliness|/services|/readiness/details)?$'),
    ({'GET'}, r'^/routes$'),
    ({'GET'}, r'^/settings$'),
    ({'GET'}, r'^/get/config/callbacks$'),
    ({'GET', 'POST'}, r'^/config/(list|update|yaml|field/(info|update|delete)|callback/delete)$'),
    ({'GET', 'PATCH'}, r'^/config/(block_requests_for_models_without_pricing|cost_discount_config|cost_margin_config)$'),
    ({'GET'}, r'^/public/(litellm_model_cost_map|providers|providers/fields|model_hub|mcp_hub)$'),
    ({'GET', 'POST'}, r'^/model/(info|new|update|delete|block|unblock|metrics|metrics/exceptions|metrics/slow_responses|settings|deprecations)$'),
    ({'PATCH'}, r'^/model/[^/]+/update$'),
    ({'GET'}, r'^/model_group/info$'),
    ({'GET', 'POST'}, r'^/credentials$'),
    ({'GET', 'PATCH', 'DELETE'}, r'^/credentials/(by_name/|by_model/)?[^/]+$'),
    ({'GET', 'POST'}, r'^/key/(generate|list|info|update|delete|block|unblock|regenerate|health|aliases|spend/report|service-account/generate)$'),
    ({'POST'}, r'^/key/[^/]+/(regenerate|reset_spend)$'),
    ({'POST'}, r'^/v2/key/info$'),
    ({'GET', 'POST'}, r'^/team/(new|list|info|update|delete|block|unblock|available|model/add|model/delete|spend/report|spend/by_user|daily/activity|daily/activity/aggregated|member_add|member_delete|member_update|permissions_list|permissions_update)$'),
    ({'GET', 'POST'}, r'^/budget/(new|list|info|update|delete|settings)$'),
    ({'GET', 'POST'}, r'^/customer/(new|list|info|update|delete|block|unblock|daily/activity)$'),
    ({'GET', 'POST', 'PUT'}, r'^/v1/mcp/server$'),
    ({'GET'}, r'^/v1/mcp/server/health$'),
    ({'GET', 'DELETE'}, r'^/v1/mcp/server/[^/]+$'),
    ({'GET'}, r'^/v1/mcp/tools$'),
    ({'GET', 'POST', 'PUT'}, r'^/v1/mcp/toolset$'),
    ({'GET', 'DELETE'}, r'^/v1/mcp/toolset/[^/]+$'),
    ({'GET', 'POST'}, r'^/guardrails(/list|/apply_guardrail|/ui/add_guardrail_settings|/ui/provider_specific_params|/usage/overview|/usage/logs)?$'),
    ({'GET', 'PUT', 'PATCH', 'DELETE'}, r'^/guardrails/[^/]+(/info)?$'),
    ({'GET', 'POST'}, r'^/global/spend(/models|/keys|/teams|/provider|/tags|/logs|/report|/all_tag_names|/end_users)?$'),
    ({'GET'}, r'^/spend/(logs|keys|users|tags|logs/v2)$'),
    ({'GET', 'POST'}, r'^/cache/(ping|settings|redis/info|settings/test|delete)$'),
    ({'GET'}, r'^/user/info$'),
]
_COMPILED = [(methods, re.compile(pattern)) for methods, pattern in ALLOWED_ROUTES]

_SENSITIVE_KEY = re.compile(r'(key|secret|token|password|credential_values|auth_value|authorization)', re.I)


class LiteLLMAdminError(Exception):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def route_allowed(method: str, path: str) -> bool:
    path = '/' + path.lstrip('/')
    method = method.upper()
    return any(method in methods and pattern.match(path) for methods, pattern in _COMPILED)


def redact(value: Any, depth: int = 0) -> Any:
    """Replace values of secret-looking keys before anything is written to the audit log."""
    if depth > 6:
        return '…'
    if isinstance(value, dict):
        return {k: ('***' if _SENSITIVE_KEY.search(str(k)) else redact(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:20]]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + '…'
    return value


def record_admin_event(action: str, actor: str, details: Dict[str, Any]) -> None:
    try:
        safe = redact(details)
        with SessionLocal() as session:
            session.add(PolicyAuditEvent(
                policy_id=None, action=action, actor=actor or 'system',
                event_hash=hashlib.sha256(json.dumps({'action': action, 'actor': actor, 'details': safe}, sort_keys=True, default=str).encode()).hexdigest(),
                details=json.dumps(safe, default=str), created_at=datetime.utcnow(),
            ))
            session.commit()
    except Exception:
        pass


class LiteLLMAdminClient:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _headers() -> Dict[str, str]:
        key = Settings.LITELLM_ADMIN_API_KEY or Settings.LITELLM_API_KEY
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if key:
            headers['Authorization'] = f'Bearer {key}'
        return headers

    async def request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None,
                      body: Optional[Any] = None, actor: str = '') -> Tuple[int, Any]:
        path = '/' + path.lstrip('/')
        method = method.upper()
        if not route_allowed(method, path):
            raise LiteLLMAdminError(403, f'{method} {path} is not an allowed LiteLLM management route')
        try:
            response = await self._client_or_create().request(
                method, f'{Settings.LITELLM_PROXY_URL}{path}', headers=self._headers(),
                params=params or None, json=body if body is not None else None,
            )
        except httpx.HTTPError as exc:
            raise LiteLLMAdminError(503, f'LiteLLM proxy request failed: {exc}') from exc
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {'raw': response.text[:2000]}
        if method != 'GET':
            record_admin_event(
                f'litellm_{method.lower()}', actor,
                {'path': path, 'status': response.status_code, 'params': params or {}, 'body': body if isinstance(body, (dict, list)) else None},
            )
        return response.status_code, payload

    async def get(self, path: str, **params) -> Any:
        status, payload = await self.request('GET', path, params=params)
        if status >= 400:
            raise LiteLLMAdminError(status, payload)
        return payload

    async def post(self, path: str, body: Any, actor: str) -> Any:
        status, payload = await self.request('POST', path, body=body, actor=actor)
        if status >= 400:
            raise LiteLLMAdminError(status, payload)
        return payload

    async def delete(self, path: str, actor: str, body: Any = None) -> Any:
        status, payload = await self.request('DELETE', path, body=body, actor=actor)
        if status >= 400:
            raise LiteLLMAdminError(status, payload)
        return payload

    async def safe_get(self, path: str, **params) -> Any:
        try:
            return await self.get(path, **params)
        except LiteLLMAdminError as exc:
            return {'error': exc.detail, 'status': exc.status_code}

    # ------------------------------------------------------------------
    # Credentials (provider keys stored encrypted in the proxy database)
    # ------------------------------------------------------------------
    @staticmethod
    def credential_name(provider: str) -> str:
        return f'{provider}-default'

    async def list_credentials(self) -> list:
        data = await self.safe_get('/credentials')
        if isinstance(data, dict) and 'credentials' in data:
            return data['credentials']
        return []

    async def store_provider_credential(self, provider: str, api_key: str, actor: str, extra: Optional[Dict[str, str]] = None) -> Any:
        values = {'api_key': api_key, **(extra or {})}
        body = {
            'credential_name': self.credential_name(provider),
            'credential_info': {'custom_llm_provider': provider, 'created_by': actor, 'created_at': datetime.utcnow().isoformat() + 'Z'},
            'credential_values': values,
        }
        existing = {c.get('credential_name') for c in await self.list_credentials()}
        if body['credential_name'] in existing:
            status, payload = await self.request('PATCH', f"/credentials/{body['credential_name']}", body=body, actor=actor)
        else:
            status, payload = await self.request('POST', '/credentials', body=body, actor=actor)
        if status >= 400:
            raise LiteLLMAdminError(status, payload)
        return payload

    async def delete_provider_credential(self, provider: str, actor: str) -> Any:
        return await self.delete(f'/credentials/{self.credential_name(provider)}', actor=actor)

    # ------------------------------------------------------------------
    # Overview
    # ------------------------------------------------------------------
    async def overview(self) -> Dict[str, Any]:
        readiness = await self.safe_get('/health/readiness')
        models = await self.safe_get('/model/info')
        credentials = await self.list_credentials()
        keys = await self.safe_get('/key/list', return_full_object='true', page=1, size=100)
        teams = await self.safe_get('/team/list')
        mcp = await self.safe_get('/v1/mcp/server')
        guardrails = await self.safe_get('/guardrails/list')
        callbacks = await self.safe_get('/get/config/callbacks')
        spend_models = await self.safe_get('/global/spend/models')
        cache = await self.safe_get('/cache/settings')

        def _count(value: Any, key: Optional[str] = None) -> Optional[int]:
            if isinstance(value, dict):
                if key and isinstance(value.get(key), list):
                    return len(value[key])
                if 'total_count' in value:
                    return value['total_count']
                return None
            return len(value) if isinstance(value, list) else None

        return {
            'proxy_url': Settings.LITELLM_PROXY_URL,
            'readiness': readiness,
            'counts': {
                'models': _count(models, 'data'),
                'credentials': len(credentials),
                'keys': _count(keys, 'keys'),
                'teams': _count(teams),
                'mcp_servers': _count(mcp),
                'guardrails': _count(guardrails, 'guardrails'),
            },
            'callbacks': callbacks.get('callbacks') if isinstance(callbacks, dict) else callbacks,
            'cache': cache,
            'spend_by_model': spend_models if isinstance(spend_models, list) else [],
            'admin_key_is_master': not Settings.LITELLM_ADMIN_API_KEY or Settings.LITELLM_ADMIN_API_KEY == Settings.LITELLM_API_KEY,
        }


litellm_admin = LiteLLMAdminClient()
