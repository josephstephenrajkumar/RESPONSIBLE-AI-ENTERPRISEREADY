"""Typed client for the Activepieces REST API (community edition, 0.92.x).

The gateway is the only caller: it signs in with a service account, keeps the 7-day
user JWT in memory and re-authenticates once on 401. Every method maps to one
`/api/v1` route; see docs/ACTIVEPIECES_INTEGRATION.md for the API review.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx

from app.config import Settings


class ActivepiecesError(Exception):
    def __init__(self, status_code: int, detail: Any):
        super().__init__(f'activepieces {status_code}: {detail}')
        self.status_code = status_code
        self.detail = detail


class ActivepiecesClient:
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (base_url or Settings.ACTIVEPIECES_API_URL).rstrip('/')
        self._client: Optional[httpx.AsyncClient] = None
        self._token: Optional[str] = None
        self._token_at: float = 0.0
        self.project_id: Optional[str] = None
        self.platform_id: Optional[str] = None
        self.user_id: Optional[str] = None

    # ------------------------------------------------------------------ plumbing
    @property
    def api(self) -> str:
        return f'{self.base_url}/api/v1'

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def forget_session(self) -> None:
        self._token = None
        self._token_at = 0.0

    @property
    def signed_in(self) -> bool:
        # Activepieces user tokens live 7 days; refresh a day early.
        return bool(self._token) and (time.time() - self._token_at) < 6 * 24 * 3600

    async def _request(self, method: str, path: str, *, json: Any = None, params: Optional[Dict[str, Any]] = None,
                       auth: bool = True, files: Any = None, data: Any = None, timeout: Optional[float] = None,
                       _retry: bool = True) -> Tuple[int, Any]:
        if auth and not self.signed_in:
            await self.sign_in()
        headers: Dict[str, str] = {'Accept': 'application/json'}
        if auth and self._token:
            headers['Authorization'] = f'Bearer {self._token}'
        try:
            response = await self._client_or_create().request(
                method, f'{self.api}{path}', headers=headers, json=json, params=params, files=files, data=data,
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise ActivepiecesError(503, f'request failed: {exc}') from exc
        if response.status_code == 401 and auth and _retry:
            self.forget_session()
            await self.sign_in()
            return await self._request(method, path, json=json, params=params, auth=auth, files=files, data=data,
                                       timeout=timeout, _retry=False)
        try:
            payload: Any = response.json() if response.content else None
        except ValueError:
            payload = {'raw': response.text[:2000]}
        return response.status_code, payload

    async def _ok(self, method: str, path: str, **kwargs) -> Any:
        status, payload = await self._request(method, path, **kwargs)
        if status >= 400:
            raise ActivepiecesError(status, payload)
        return payload

    # ------------------------------------------------------------------ session
    async def ping(self) -> bool:
        try:
            status, _ = await self._request('GET', '/flags', auth=False, timeout=5.0)
        except ActivepiecesError:
            return False
        return status == 200

    async def sign_in(self) -> Dict[str, Any]:
        """Sign in the service account. On a fresh instance the first sign-up creates the
        platform and makes this account its administrator."""
        email, password = Settings.ACTIVEPIECES_SERVICE_EMAIL, Settings.ACTIVEPIECES_SERVICE_PASSWORD
        if not password:
            raise ActivepiecesError(500, 'ACTIVEPIECES_SERVICE_PASSWORD is not configured')
        status, payload = await self._request('POST', '/authentication/sign-in',
                                              json={'email': email, 'password': password}, auth=False)
        if status in (400, 401, 403, 404):
            status, payload = await self._request('POST', '/authentication/sign-up', json={
                'email': email, 'password': password, 'firstName': 'Workflow', 'lastName': 'Service',
                'trackEvents': False, 'newsLetter': False,
            }, auth=False)
        if status not in (200, 201) or not isinstance(payload, dict) or not payload.get('token'):
            raise ActivepiecesError(status, payload)
        self._token = payload['token']
        self._token_at = time.time()
        self.project_id = payload.get('projectId')
        self.platform_id = payload.get('platformId')
        self.user_id = payload.get('id')
        return payload

    def require_project(self) -> str:
        if not self.project_id:
            raise ActivepiecesError(500, 'service account has no project; sign-in did not return projectId')
        return self.project_id

    # ------------------------------------------------------------------ pieces
    async def get_piece(self, name: str) -> Optional[Dict[str, Any]]:
        status, payload = await self._request('GET', f'/pieces/{name}')
        if status == 404:
            return None
        if status >= 400:
            raise ActivepiecesError(status, payload)
        return payload

    async def install_piece_archive(self, path: str, name: str, version: str) -> Dict[str, Any]:
        with open(path, 'rb') as handle:
            archive = handle.read()
        status, payload = await self._request(
            'POST', '/pieces',
            files={'pieceArchive': (os.path.basename(path), archive, 'application/gzip')},
            data={'pieceName': name, 'pieceVersion': version, 'packageType': 'ARCHIVE', 'scope': 'PLATFORM'},
            timeout=600.0,
        )
        if status == 409:
            return {'already_installed': True, 'name': name, 'version': version}
        if status >= 400:
            raise ActivepiecesError(status, payload)
        return payload or {}

    # ------------------------------------------------------------------ AI providers
    async def list_ai_providers(self) -> list:
        payload = await self._ok('GET', '/ai-providers', params={'projectId': self.require_project()})
        if isinstance(payload, dict) and 'data' in payload:
            return payload['data']
        return payload if isinstance(payload, list) else []

    async def list_ai_provider_configs(self) -> list:
        status, payload = await self._request('GET', '/ai-providers/configs')
        if status >= 400:
            return []
        if isinstance(payload, dict) and 'data' in payload:
            return payload['data']
        return payload if isinstance(payload, list) else []

    async def create_ai_provider(self, body: Dict[str, Any]) -> Dict[str, Any]:
        return await self._ok('POST', '/ai-providers', json=body)

    async def update_ai_provider(self, provider_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return await self._ok('POST', f'/ai-providers/{provider_id}', json=body)

    # ------------------------------------------------------------------ connections
    async def upsert_custom_auth_connection(self, external_id: str, display_name: str, piece_name: str,
                                            props: Dict[str, Any]) -> Dict[str, Any]:
        body = {
            'externalId': external_id, 'displayName': display_name, 'pieceName': piece_name,
            'projectId': self.require_project(), 'type': 'CUSTOM_AUTH',
            'value': {'type': 'CUSTOM_AUTH', 'props': props},
        }
        return await self._ok('POST', '/app-connections', json=body)

    async def delete_connection(self, connection_id: str) -> None:
        status, payload = await self._request('DELETE', f'/app-connections/{connection_id}')
        if status >= 400 and status != 404:
            raise ActivepiecesError(status, payload)

    # ------------------------------------------------------------------ flows
    async def create_flow(self, display_name: str, external_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {'displayName': display_name, 'projectId': self.require_project(), 'externalId': external_id}
        if metadata:
            body['metadata'] = metadata
        return await self._ok('POST', '/flows', json=body)

    async def apply_operation(self, flow_id: str, operation: str, request: Any) -> Dict[str, Any]:
        return await self._ok('POST', f'/flows/{flow_id}', json={'type': operation, 'request': request})

    async def import_flow(self, flow_id: str, display_name: str, trigger: Dict[str, Any]) -> Dict[str, Any]:
        return await self.apply_operation(flow_id, 'IMPORT_FLOW', {
            'displayName': display_name, 'trigger': trigger, 'schemaVersion': None, 'notes': None,
        })

    async def publish_flow(self, flow_id: str) -> Dict[str, Any]:
        return await self.apply_operation(flow_id, 'LOCK_AND_PUBLISH', {})

    async def set_flow_status(self, flow_id: str, enabled: bool) -> Dict[str, Any]:
        return await self.apply_operation(flow_id, 'CHANGE_STATUS', {'status': 'ENABLED' if enabled else 'DISABLED'})

    async def get_flow(self, flow_id: str) -> Optional[Dict[str, Any]]:
        status, payload = await self._request('GET', f'/flows/{flow_id}')
        if status == 404:
            return None
        if status >= 400:
            raise ActivepiecesError(status, payload)
        return payload

    async def delete_flow(self, flow_id: str) -> None:
        status, payload = await self._request('DELETE', f'/flows/{flow_id}')
        if status >= 400 and status != 404:
            raise ActivepiecesError(status, payload)

    async def list_runs(self, flow_id: str, limit: int = 20) -> list:
        payload = await self._ok('GET', '/flow-runs', params={'projectId': self.require_project(), 'flowId': flow_id, 'limit': limit})
        if isinstance(payload, dict):
            return payload.get('data') or []
        return payload if isinstance(payload, list) else []

    # ------------------------------------------------------------------ chat (public webhook)
    async def chat(self, flow_id: str, chat_id: str, message: str, timeout: float = 150.0) -> Tuple[int, Any]:
        return await self._request('POST', f'/webhooks/{flow_id}/sync', json={'chatId': chat_id, 'message': message},
                                   auth=False, timeout=timeout)


activepieces = ActivepiecesClient()
