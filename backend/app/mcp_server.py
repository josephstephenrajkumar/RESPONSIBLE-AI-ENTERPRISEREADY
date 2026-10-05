"""MCP server: publishes selected workflow apps as tools for external agents.

External MCP clients (Amazon Quick Suite Actions integrations, Claude, LiteLLM's MCP gateway,
IDE agents) connect to `POST /mcp` with the streamable-HTTP transport and see one tool per
published workflow app in their tenant. A tool call sends one turn to the app's published
flow, exactly like `POST /workflows/apps/{id}/chat`, so the Responsible AI pipeline, budgets
and metering of the app apply unchanged.

Authentication on /mcp: an MCP key (`rai_mcp_...`, issued from the Workflow Apps screen,
stored as a SHA-256 hash) or any bearer the gateway already accepts (Cognito JWT, app token).
`/.well-known/oauth-protected-resource` points OAuth-capable clients at Cognito.
docs/MCP_PUBLISHING.md
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, String

from app import workflow_apps
from app.activepieces_client import ActivepiecesError
from app.auth import AuthenticatedUser, get_current_user, require_workflow_admin
from app.config import Settings
from app.database import Base, SessionLocal, engine
from app.litellm_admin import record_admin_event
from app.workflow_apps import WorkflowApp, _get_app, _require_enabled

KEY_PREFIX = 'rai_mcp_'
PROTOCOL_VERSIONS = ['2025-06-18', '2025-03-26', '2024-11-05']
SERVER_NAME = 'responsible-ai-gateway'
SERVER_VERSION = '1.0.0'
TOOL_NAME_RE = re.compile(r'^[a-z][a-z0-9_]{1,62}$')
INSTRUCTIONS = ('Each tool is a governed workflow app of the Responsible AI Enterprise Gateway. Send the user request as '
                '`message`. Every call without `session_id` starts a fresh conversation; pass the `session_id` returned in '
                'structuredContent on follow-up turns of the same user to keep context. Answers are markdown.')
MAX_BODY_BYTES = 256 * 1024
MAX_BATCH = 10
LAST_USED_WRITE_INTERVAL = timedelta(minutes=1)


class McpTool(Base):
    __tablename__ = 'workflow_mcp_tools'

    app_id = Column(String(40), primary_key=True)
    tenant_id = Column(String(160), nullable=False, default='default', index=True)
    tool_name = Column(String(64), nullable=False)
    description = Column(String(1000), nullable=False, default='')
    published = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class McpKey(Base):
    __tablename__ = 'workflow_mcp_keys'

    key_hash = Column(String(64), primary_key=True)
    key_id = Column(String(24), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    tenant_id = Column(String(160), nullable=False, default='default', index=True)
    created_by = Column(String(200), nullable=False, default='')
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


def ensure_tables() -> None:
    McpTool.__table__.create(bind=engine, checkfirst=True)
    McpKey.__table__.create(bind=engine, checkfirst=True)


# ----------------------------------------------------------------------------- keys
def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def issue_key(name: str, tenant_id: str, created_by: str) -> Dict[str, str]:
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    key_id = 'mk_' + secrets.token_hex(6)
    with SessionLocal() as session:
        session.add(McpKey(key_hash=hash_key(key), key_id=key_id, name=name.strip()[:120] or 'MCP key', tenant_id=tenant_id, created_by=created_by))
        session.commit()
    return {'key_id': key_id, 'key': key}


def revoke_key(key_id: str, tenant_id: str) -> bool:
    with SessionLocal() as session:
        row = session.query(McpKey).filter_by(key_id=key_id, tenant_id=tenant_id, revoked_at=None).first()
        if row is None:
            return False
        row.revoked_at = datetime.utcnow()
        session.commit()
        return True


def authenticate_key(key: str) -> Optional[Dict[str, str]]:
    if not key or not key.startswith(KEY_PREFIX):
        return None
    with SessionLocal() as session:
        row = session.get(McpKey, hash_key(key))
        if row is None or row.revoked_at is not None:
            return None
        now = datetime.utcnow()
        if row.last_used_at is None or now - row.last_used_at > LAST_USED_WRITE_INTERVAL:
            row.last_used_at = now
            session.commit()
        return {'tenant_id': row.tenant_id, 'key_id': row.key_id, 'name': row.name}


def list_keys(tenant_id: str) -> List[Dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.query(McpKey).filter_by(tenant_id=tenant_id).order_by(McpKey.created_at.desc()).all()
        return [{'key_id': r.key_id, 'name': r.name, 'created_by': r.created_by, 'created_at': r.created_at.isoformat() + 'Z' if r.created_at else None,
                 'last_used_at': r.last_used_at.isoformat() + 'Z' if r.last_used_at else None, 'revoked': r.revoked_at is not None} for r in rows]


# ----------------------------------------------------------------------------- tools
def slugify(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '_', (name or '').lower()).strip('_')
    if not slug or not slug[0].isalpha():
        slug = f'app_{slug}' if slug else 'app'
    return slug[:63]


def tool_row(app_id: str) -> Optional[McpTool]:
    with SessionLocal() as session:
        return session.get(McpTool, app_id)


def serialize_tool(row: McpTool, app: Optional[WorkflowApp] = None) -> Dict[str, Any]:
    return {'app_id': row.app_id, 'tool_name': row.tool_name, 'description': row.description, 'published': bool(row.published),
            'app_name': app.name if app else None, 'app_status': app.status if app else None,
            'updated_at': row.updated_at.isoformat() + 'Z' if row.updated_at else None}


def published_tools(tenant_id: str) -> List[Dict[str, Any]]:
    """Tools an MCP client in this tenant can see: enabled here and the app published on the engine."""
    with SessionLocal() as session:
        rows = session.query(McpTool).filter_by(tenant_id=tenant_id, published=True).all()
        apps = {a.id: a for a in session.query(WorkflowApp).filter(WorkflowApp.id.in_([r.app_id for r in rows])).all()} if rows else {}
    out = []
    for row in rows:
        app = apps.get(row.app_id)
        if app is None or app.status != 'published' or app.tenant_id != row.tenant_id:
            continue
        out.append({'row': row, 'app': app})
    return out


def tool_descriptor(row: McpTool, app: WorkflowApp) -> Dict[str, Any]:
    return {
        'name': row.tool_name,
        'title': app.name,
        'description': row.description or app.description or f'Workflow app {app.name}',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string', 'description': 'The request or question for the app.'},
                'session_id': {'type': 'string', 'description': 'Optional conversation id; reuse it to keep context across turns.'},
            },
            'required': ['message'],
        },
        'annotations': {'readOnlyHint': False, 'openWorldHint': True},
    }


# ----------------------------------------------------------------------------- admin routes
router = APIRouter(prefix='/workflows/mcp', tags=['workflow-mcp'])


class KeyCreate(BaseModel):
    name: str = Field(default='MCP key', max_length=120)


class ToolUpdate(BaseModel):
    published: bool
    tool_name: Optional[str] = Field(default=None, max_length=64)
    description: Optional[str] = Field(default=None, max_length=1000)


def _base_url(request: Request) -> str:
    if Settings.PUBLIC_BASE_URL:
        return Settings.PUBLIC_BASE_URL
    proto = request.headers.get('x-forwarded-proto', request.url.scheme)
    host = request.headers.get('x-forwarded-host', request.headers.get('host', request.url.netloc))
    return f'{proto}://{host}'


@router.get('')
def mcp_info(request: Request, user: AuthenticatedUser = Depends(require_workflow_admin)):
    base = _base_url(request)
    with SessionLocal() as session:
        rows = session.query(McpTool).filter_by(tenant_id=user.tenant_id).all()
        apps = {a.id: a for a in session.query(WorkflowApp).filter_by(tenant_id=user.tenant_id).all()}
    issuer = f'https://cognito-idp.{Settings.COGNITO_REGION}.amazonaws.com/{Settings.COGNITO_USER_POOL_ID}' if getattr(Settings, 'COGNITO_USER_POOL_ID', '') else ''
    return {
        'endpoint': f'{base}/mcp',
        'resource_metadata': f'{base}/.well-known/oauth-protected-resource',
        'protocol_versions': PROTOCOL_VERSIONS,
        'oauth_issuer': issuer,
        'tools': [serialize_tool(r, apps.get(r.app_id)) for r in rows],
        'keys': list_keys(user.tenant_id),
    }


@router.post('/keys', status_code=201)
def mcp_issue_key(payload: KeyCreate, user: AuthenticatedUser = Depends(require_workflow_admin)):
    issued = issue_key(payload.name, user.tenant_id, user.email or user.user_id)
    record_admin_event('mcp_key_issued', user.email or user.user_id, {'key_id': issued['key_id'], 'name': payload.name})
    return {**issued, 'name': payload.name, 'note': 'Shown once. Store it in the client (Quick integration, Claude, LiteLLM MCP) and never in a file in git.'}


@router.delete('/keys/{key_id}')
def mcp_revoke_key(key_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    if not revoke_key(key_id, user.tenant_id):
        raise HTTPException(status_code=404, detail='Key not found or already revoked')
    record_admin_event('mcp_key_revoked', user.email or user.user_id, {'key_id': key_id})
    return {'revoked': key_id}


@router.put('/tools/{app_id}')
def mcp_update_tool(app_id: str, payload: ToolUpdate, user: AuthenticatedUser = Depends(require_workflow_admin)):
    app = _get_app(app_id, user)
    name = slugify(payload.tool_name) if payload.tool_name else None
    with SessionLocal() as session:
        row = session.get(McpTool, app_id)
        if row is None:
            row = McpTool(app_id=app_id, tenant_id=user.tenant_id, tool_name=name or slugify(app.name), description=payload.description or app.description or '')
            session.add(row)
        if name:
            row.tool_name = name
        if payload.description is not None:
            row.description = payload.description
        if not TOOL_NAME_RE.match(row.tool_name):
            raise HTTPException(status_code=400, detail='Tool name must be lowercase letters, digits and underscores, starting with a letter')
        clash = session.query(McpTool).filter(McpTool.tenant_id == user.tenant_id, McpTool.tool_name == row.tool_name, McpTool.app_id != app_id).first()
        if clash is not None:
            raise HTTPException(status_code=409, detail=f'Tool name {row.tool_name!r} is already used by app {clash.app_id}')
        row.published = payload.published
        session.commit()
        session.refresh(row)
        out = serialize_tool(row, app)
    record_admin_event('mcp_tool_updated', user.email or user.user_id, {'app_id': app_id, 'tool_name': out['tool_name'], 'published': payload.published})
    return out


def delete_tool(app_id: str) -> None:
    with SessionLocal() as session:
        row = session.get(McpTool, app_id)
        if row is not None:
            session.delete(row)
            session.commit()


# ----------------------------------------------------------------------------- MCP endpoint
mcp_router = APIRouter(tags=['mcp'])


class McpPrincipal(BaseModel):
    tenant_id: str
    subject: str
    via: str


async def mcp_principal(request: Request) -> McpPrincipal:
    header = request.headers.get('authorization', '')
    token = header[7:].strip() if header.lower().startswith('bearer ') else ''
    if token.startswith(KEY_PREFIX):
        key = authenticate_key(token)
        if key is None:
            raise _unauthorized(request, 'Invalid or revoked MCP key')
        return McpPrincipal(tenant_id=key['tenant_id'], subject=f"mcp-key:{key['key_id']}", via='mcp-key')
    if not token and Settings.AUTH_REQUIRED:
        raise _unauthorized(request, 'Authorization required')
    try:
        creds = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token) if token else None
        user = await get_current_user(creds, None)
    except HTTPException as exc:
        raise _unauthorized(request, str(exc.detail))
    if 'workflow-app' in (user.groups or ()):
        # A workflow app token must not call back into the MCP server (app-to-app loops, budget hopping).
        raise HTTPException(status_code=403, detail='Workflow app tokens cannot use the MCP endpoint')
    return McpPrincipal(tenant_id=user.tenant_id, subject=user.email or user.user_id, via='bearer')


def _unauthorized(request: Request, detail: str) -> HTTPException:
    base = _base_url(request)
    return HTTPException(status_code=401, detail=detail, headers={'WWW-Authenticate': f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource"'})


def _rpc_error(id_: Any, code: int, message: str, data: Any = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {'code': code, 'message': message}
    if data is not None:
        err['data'] = data
    return {'jsonrpc': '2.0', 'id': id_, 'error': err}


def _rpc_result(id_: Any, result: Any) -> Dict[str, Any]:
    return {'jsonrpc': '2.0', 'id': id_, 'result': result}


async def call_tool(principal: McpPrincipal, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    match = next((t for t in published_tools(principal.tenant_id) if t['row'].tool_name == name), None)
    if match is None:
        return {'content': [{'type': 'text', 'text': f'Unknown tool {name!r}'}], 'isError': True}
    message = str(arguments.get('message') or '').strip()
    if not message:
        return {'content': [{'type': 'text', 'text': 'Argument `message` is required'}], 'isError': True}
    app: WorkflowApp = match['app']
    # A fresh conversation per call unless the client carries its own session id: users behind one key never share memory.
    session_id = str(arguments.get('session_id') or f'mcp-{secrets.token_hex(8)}')
    started = time.time()
    try:
        status, body = await workflow_apps.activepieces.chat(app.ap_flow_id, session_id, message)
    except ActivepiecesError as exc:
        result = {'content': [{'type': 'text', 'text': f'Workflow engine error: {exc}'}], 'isError': True}
    else:
        if status != 200:
            result = {'content': [{'type': 'text', 'text': f'The app failed (engine status {status}): {json.dumps(body)[:500]}'}], 'isError': True}
        else:
            answer = body.get('value') if isinstance(body, dict) else body
            text = answer if isinstance(answer, str) else json.dumps(answer)
            result = {'content': [{'type': 'text', 'text': text}],
                      'structuredContent': {'answer': answer, 'session_id': session_id, 'app_id': app.id, 'latency_ms': int((time.time() - started) * 1000)},
                      'isError': False}
    try:
        record_admin_event('mcp_tool_call', principal.subject, {'tool': name, 'app_id': app.id, 'via': principal.via, 'is_error': bool(result.get('isError')), 'latency_ms': int((time.time() - started) * 1000)})
    except Exception:  # pragma: no cover - auditing must never break the call
        pass
    return result


async def handle_message(principal: McpPrincipal, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One JSON-RPC message → response dict, or None for notifications."""
    if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or 'method' not in msg:
        return _rpc_error(msg.get('id') if isinstance(msg, dict) else None, -32600, 'Invalid Request')
    method, params, id_ = msg['method'], msg.get('params') or {}, msg.get('id')
    is_notification = 'id' not in msg
    if method == 'initialize':
        requested = str(params.get('protocolVersion') or PROTOCOL_VERSIONS[0])
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _rpc_result(id_, {'protocolVersion': version, 'capabilities': {'tools': {'listChanged': False}},
                                 'serverInfo': {'name': SERVER_NAME, 'title': 'Responsible AI Enterprise Gateway', 'version': SERVER_VERSION},
                                 'instructions': INSTRUCTIONS})
    if method.startswith('notifications/'):
        return None
    if method == 'ping':
        return _rpc_result(id_, {})
    if method == 'tools/list':
        tools = [tool_descriptor(t['row'], t['app']) for t in published_tools(principal.tenant_id)]
        return _rpc_result(id_, {'tools': tools})
    if method == 'tools/call':
        name = str(params.get('name') or '')
        arguments = params.get('arguments') or {}
        if not isinstance(arguments, dict):
            return _rpc_error(id_, -32602, 'arguments must be an object')
        return _rpc_result(id_, await call_tool(principal, name, arguments))
    if method == 'resources/list':
        return _rpc_result(id_, {'resources': []})
    if method == 'resources/templates/list':
        return _rpc_result(id_, {'resourceTemplates': []})
    if method == 'prompts/list':
        return _rpc_result(id_, {'prompts': []})
    if is_notification:
        return None
    return _rpc_error(id_, -32601, f'Method not found: {method}')


@mcp_router.post('/mcp')
async def mcp_post(request: Request, principal: McpPrincipal = Depends(mcp_principal)):
    _require_enabled()
    try:
        if int(request.headers.get('content-length') or 0) > MAX_BODY_BYTES:
            return JSONResponse(status_code=413, content=_rpc_error(None, -32600, f'Request body over {MAX_BODY_BYTES} bytes'))
    except ValueError:
        pass
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content=_rpc_error(None, -32600, f'Request body over {MAX_BODY_BYTES} bytes'))
    try:
        payload = json.loads(raw.decode('utf-8') or 'null')
    except ValueError:
        return JSONResponse(status_code=400, content=_rpc_error(None, -32700, 'Parse error'))
    messages = payload if isinstance(payload, list) else [payload]
    if not messages or payload is None:
        return JSONResponse(status_code=400, content=_rpc_error(None, -32600, 'Empty batch'))
    if len(messages) > MAX_BATCH:
        return JSONResponse(status_code=400, content=_rpc_error(None, -32600, f'Batch over {MAX_BATCH} messages'))
    responses = [r for r in [await handle_message(principal, m) for m in messages] if r is not None]
    requested = request.headers.get('mcp-protocol-version', '')
    version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    if not responses:
        return Response(status_code=202, headers={'MCP-Protocol-Version': version})
    body = responses if isinstance(payload, list) else responses[0]
    return JSONResponse(content=body, headers={'MCP-Protocol-Version': version})


@mcp_router.get('/mcp')
async def mcp_get():
    # No server-initiated streams: clients use plain JSON responses.
    return Response(status_code=405, headers={'Allow': 'POST, DELETE'})


@mcp_router.delete('/mcp')
async def mcp_delete():
    return Response(status_code=204)


@mcp_router.get('/.well-known/oauth-protected-resource')
async def oauth_protected_resource(request: Request):
    base = _base_url(request)
    issuer = f'https://cognito-idp.{Settings.COGNITO_REGION}.amazonaws.com/{Settings.COGNITO_USER_POOL_ID}' if getattr(Settings, 'COGNITO_USER_POOL_ID', '') else ''
    return {'resource': f'{base}/mcp', 'authorization_servers': [issuer] if issuer else [], 'bearer_methods_supported': ['header'],
            'scopes_supported': ['openid', 'email'], 'resource_name': 'Responsible AI Enterprise Gateway MCP'}
