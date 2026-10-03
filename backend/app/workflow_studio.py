"""Workflow Studio API: the gateway-side surface our own builder drives.

The portal builds flows with these routes only; the engine's UI is never shown. Every call is
tenant-scoped through the app registry (workflow_apps) and executed with the service session,
so the browser never holds an engine credential. docs/WORKFLOW_STUDIO_PLAN.md, sprint WS-1.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import workflow_apps
from app.activepieces_client import ActivepiecesError, activepieces
from app.auth import AuthenticatedUser, require_workflow_admin
from app.config import Settings
from app.litellm_admin import record_admin_event
from app.workflow_apps import WorkflowApp, _ap_error, _get_app, _require_enabled, setting_get, setting_set

router = APIRouter(prefix='/workflows', tags=['workflow-studio'])

# Operations the Studio may apply. Anything else (status, publish, folders, metadata) goes
# through the existing app endpoints so the registry stays authoritative.
ALLOWED_OPERATIONS = {
    'UPDATE_TRIGGER', 'ADD_ACTION', 'UPDATE_ACTION', 'DELETE_ACTION', 'MOVE_ACTION', 'DUPLICATE_ACTION',
    'CHANGE_NAME', 'SAVE_SAMPLE_DATA', 'USE_AS_DRAFT', 'ADD_BRANCH', 'DELETE_BRANCH', 'DUPLICATE_BRANCH',
    'SET_SKIP_ACTION', 'UPDATE_SAMPLE_DATA_INFO',
}
CONNECTION_TYPES = {'CUSTOM_AUTH', 'SECRET_TEXT', 'BASIC_AUTH', 'OAUTH2'}
SLUG_RE = re.compile(r'[^a-z0-9]+')


# ----------------------------------------------------------------------------- schemas
class OperationRequest(BaseModel):
    type: str
    request: Any = Field(default_factory=dict)


class OptionsRequest(BaseModel):
    piece_name: str
    piece_version: str
    action_or_trigger_name: str
    property_name: str
    input: Dict[str, Any] = Field(default_factory=dict)
    search_value: str = ''


class ConnectionCreate(BaseModel):
    piece_name: str
    display_name: str = Field(..., min_length=1, max_length=120)
    auth_type: str = 'CUSTOM_AUTH'
    props: Dict[str, Any] = Field(default_factory=dict)   # CUSTOM_AUTH
    secret_text: str = ''                                   # SECRET_TEXT
    username: str = ''                                      # BASIC_AUTH
    password: str = ''
    oauth2: Dict[str, Any] = Field(default_factory=dict)    # OAUTH2: client_id, client_secret, code, redirect_url, scope, props


class OAuthUrlRequest(BaseModel):
    piece_name: str
    client_id: str
    redirect_url: str
    scope: str = ''
    props: Dict[str, Any] = Field(default_factory=dict)


class CatalogueUpdate(BaseModel):
    pieces: List[str]


# ----------------------------------------------------------------------------- helpers
def curated_pieces() -> List[str]:
    stored = setting_get('studio_pieces')
    if isinstance(stored, list) and stored:
        return [str(p) for p in stored]
    return list(Settings.WORKFLOW_STUDIO_PIECES)


def _slug(text: str) -> str:
    return SLUG_RE.sub('-', text.lower()).strip('-')[:40] or 'conn'


def flatten_steps(trigger: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Depth-first list of every step (trigger first) with its parent and branch index, for the editor."""
    out: List[Dict[str, Any]] = []

    def visit(step: Optional[Dict[str, Any]], parent: Optional[str], branch: Optional[int], depth: int) -> None:
        while step:
            settings = step.get('settings') or {}
            out.append({
                'name': step.get('name'), 'displayName': step.get('displayName'), 'type': step.get('type'), 'valid': step.get('valid'),
                'skip': step.get('skip', False), 'parent': parent, 'branch': branch, 'depth': depth,
                'pieceName': settings.get('pieceName'), 'pieceVersion': settings.get('pieceVersion'),
                'actionName': settings.get('actionName') or settings.get('triggerName'),
                'input': settings.get('input') or {}, 'propertySettings': settings.get('propertySettings') or {},
                'errorHandlingOptions': settings.get('errorHandlingOptions') or {},
                'sourceCode': settings.get('sourceCode'), 'items': settings.get('items'),
                'branches': settings.get('branches'), 'executionType': settings.get('executionType'),
                'sampleData': settings.get('sampleData'),
            })
            if step.get('type') == 'ROUTER':
                for index, child in enumerate(step.get('children') or []):
                    visit(child, step.get('name'), index, depth + 1)
            if step.get('type') == 'LOOP_ON_ITEMS':
                visit(step.get('firstLoopAction'), step.get('name'), None, depth + 1)
            step = step.get('nextAction')
    visit(trigger, None, None, 0)
    return out


def _app_connection_prefix(app: WorkflowApp) -> str:
    return f'{app.id}-'


async def _flow_payload(app: WorkflowApp) -> Dict[str, Any]:
    flow = await activepieces.get_flow(app.ap_flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail='The engine no longer has this flow')
    version = flow.get('version') or {}
    connections = [c for c in await activepieces.list_connections() if str(c.get('externalId', '')).startswith(_app_connection_prefix(app))]
    return {
        'app': workflow_apps.serialize(app),
        'flow': {'id': flow.get('id'), 'status': flow.get('status'), 'publishedVersionId': flow.get('publishedVersionId'), 'updated': flow.get('updated')},
        'version': {'id': version.get('id'), 'displayName': version.get('displayName'), 'state': version.get('state'), 'valid': version.get('valid'),
                    'updated': version.get('updated'), 'trigger': version.get('trigger')},
        'steps': flatten_steps(version.get('trigger')),
        'connections': [{'id': c.get('id'), 'externalId': c.get('externalId'), 'displayName': c.get('displayName'), 'pieceName': c.get('pieceName'),
                         'type': c.get('type'), 'status': c.get('status')} for c in connections],
    }


# ----------------------------------------------------------------------------- catalogue
@router.get('/studio/pieces')
async def studio_pieces(search: str = '', user: AuthenticatedUser = Depends(require_workflow_admin), all: bool = False):
    """Pieces available to the Studio: the curated catalogue, or every engine piece when all=true (catalogue management)."""
    _require_enabled()
    try:
        pieces = await activepieces.list_pieces(search)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    allow = [] if all else curated_pieces()
    index = {p.get('name'): p for p in pieces if isinstance(p, dict)}
    ordered = [index[n] for n in allow if n in index] + ([p for p in pieces if isinstance(p, dict) and p.get('name') not in allow] if not allow else [])
    if search:
        term = search.lower()
        ordered = [p for p in ordered if term in (p.get('displayName') or '').lower() or term in (p.get('name') or '').lower() or term in (p.get('description') or '').lower()]
    return {'pieces': [{'name': p.get('name'), 'displayName': p.get('displayName'), 'description': p.get('description'), 'logoUrl': p.get('logoUrl'),
                        'version': p.get('version'), 'actions': p.get('actions'), 'triggers': p.get('triggers'), 'categories': p.get('categories'),
                        'auth': p.get('auth'), 'pieceType': p.get('pieceType')} for p in ordered],
            'curated': allow}


@router.get('/studio/pieces/{name:path}')
async def studio_piece(name: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    try:
        piece = await activepieces.get_piece(name)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    if piece is None:
        raise HTTPException(status_code=404, detail='Piece not found')
    return piece


@router.get('/studio/catalogue')
def studio_catalogue(user: AuthenticatedUser = Depends(require_workflow_admin)):
    return {'pieces': curated_pieces(), 'default': list(Settings.WORKFLOW_STUDIO_PIECES)}


@router.put('/studio/catalogue')
def studio_catalogue_update(payload: CatalogueUpdate, user: AuthenticatedUser = Depends(require_workflow_admin)):
    pieces = [p.strip() for p in payload.pieces if p.strip()]
    setting_set('studio_pieces', pieces)
    record_admin_event('workflow_studio_catalogue', user.email or user.user_id, {'pieces': pieces})
    return {'pieces': curated_pieces()}


# ----------------------------------------------------------------------------- flow editing
@router.get('/apps/{app_id}/studio/flow')
async def studio_flow(app_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        return await _flow_payload(app)
    except ActivepiecesError as exc:
        raise _ap_error(exc)


@router.post('/apps/{app_id}/studio/operations')
async def studio_operation(app_id: str, payload: OperationRequest, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    if payload.type not in ALLOWED_OPERATIONS:
        raise HTTPException(status_code=400, detail=f'Operation {payload.type!r} is not available in the Studio')
    app = _get_app(app_id, user)
    try:
        await activepieces.apply_operation(app.ap_flow_id, payload.type, payload.request)
        result = await _flow_payload(app)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    if payload.type not in ('SAVE_SAMPLE_DATA', 'UPDATE_SAMPLE_DATA_INFO'):
        record_admin_event('workflow_studio_operation', user.email or user.user_id, {'app_id': app_id, 'operation': payload.type})
    return result


@router.post('/apps/{app_id}/studio/options')
async def studio_options(app_id: str, payload: OptionsRequest, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        flow = await activepieces.get_flow(app.ap_flow_id)
        version_id = ((flow or {}).get('version') or {}).get('id')
        body = {'pieceName': payload.piece_name, 'pieceVersion': payload.piece_version, 'actionOrTriggerName': payload.action_or_trigger_name,
                'propertyName': payload.property_name, 'flowId': app.ap_flow_id, 'flowVersionId': version_id, 'input': payload.input}
        if payload.search_value:
            body['searchValue'] = payload.search_value
        return await activepieces.piece_options(body)
    except ActivepiecesError as exc:
        raise _ap_error(exc)


@router.get('/apps/{app_id}/studio/versions')
async def studio_versions(app_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        versions = await activepieces.list_flow_versions(app.ap_flow_id)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    return {'versions': [{'id': v.get('id'), 'displayName': v.get('displayName'), 'state': v.get('state'), 'valid': v.get('valid'),
                          'created': v.get('created'), 'updated': v.get('updated'), 'updatedBy': v.get('updatedBy')} for v in versions if isinstance(v, dict)]}


# ----------------------------------------------------------------------------- connections
@router.get('/apps/{app_id}/studio/connections')
async def studio_connections(app_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        return {'connections': (await _flow_payload(app))['connections']}
    except ActivepiecesError as exc:
        raise _ap_error(exc)


def _connection_body(app: WorkflowApp, payload: ConnectionCreate) -> Dict[str, Any]:
    if payload.auth_type not in CONNECTION_TYPES:
        raise HTTPException(status_code=400, detail=f'auth_type must be one of {sorted(CONNECTION_TYPES)}')
    external_id = f'{app.id}-{_slug(payload.piece_name.split("/")[-1].replace("piece-", ""))}-{secrets.token_hex(3)}'
    base = {'externalId': external_id, 'displayName': payload.display_name, 'pieceName': payload.piece_name, 'type': payload.auth_type}
    if payload.auth_type == 'CUSTOM_AUTH':
        if not payload.props:
            raise HTTPException(status_code=400, detail='props are required for a custom-auth connection')
        base['value'] = {'type': 'CUSTOM_AUTH', 'props': payload.props}
    elif payload.auth_type == 'SECRET_TEXT':
        if not payload.secret_text:
            raise HTTPException(status_code=400, detail='secret_text is required')
        base['value'] = {'type': 'SECRET_TEXT', 'secret_text': payload.secret_text}
    elif payload.auth_type == 'BASIC_AUTH':
        base['value'] = {'type': 'BASIC_AUTH', 'username': payload.username, 'password': payload.password}
    else:  # OAUTH2 (authorization code exchanged by the engine)
        required = ('client_id', 'client_secret', 'code', 'redirect_url')
        missing = [k for k in required if not payload.oauth2.get(k)]
        if missing:
            raise HTTPException(status_code=400, detail=f'oauth2 fields missing: {", ".join(missing)}')
        value = {'type': 'OAUTH2', 'client_id': payload.oauth2['client_id'], 'client_secret': payload.oauth2['client_secret'],
                 'code': payload.oauth2['code'], 'redirect_url': payload.oauth2['redirect_url'], 'scope': payload.oauth2.get('scope', ''),
                 'props': payload.oauth2.get('props') or {}}
        if payload.oauth2.get('code_challenge'):
            value['code_challenge'] = payload.oauth2['code_challenge']
        if payload.oauth2.get('authorization_method'):
            value['authorization_method'] = payload.oauth2['authorization_method']
        base['value'] = value
    return base


@router.post('/apps/{app_id}/studio/connections', status_code=201)
async def studio_connection_create(app_id: str, payload: ConnectionCreate, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    body = _connection_body(app, payload)
    try:
        created = await activepieces.upsert_connection(body)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    record_admin_event('workflow_studio_connection', user.email or user.user_id, {'app_id': app_id, 'piece': payload.piece_name, 'type': payload.auth_type, 'external_id': body['externalId']})
    return {'id': created.get('id'), 'externalId': body['externalId'], 'displayName': payload.display_name, 'pieceName': payload.piece_name,
            'type': payload.auth_type, 'status': created.get('status'), 'reference': f"{{{{connections['{body['externalId']}']}}}}"}


@router.delete('/apps/{app_id}/studio/connections/{connection_id}')
async def studio_connection_delete(app_id: str, connection_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    if connection_id in (app.ap_connection_gateway_id, app.ap_connection_litellm_id):
        raise HTTPException(status_code=409, detail='The app\'s own gateway and LiteLLM connections cannot be deleted here')
    try:
        await activepieces.delete_connection(connection_id)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    return {'deleted': connection_id}


@router.post('/apps/{app_id}/studio/oauth2/authorization-url')
async def studio_oauth_url(app_id: str, payload: OAuthUrlRequest, user: AuthenticatedUser = Depends(require_workflow_admin)):
    """Authorization URL for an OAuth2 piece. The portal's own callback page relays the code back."""
    _require_enabled()
    _get_app(app_id, user)
    try:
        piece = await activepieces.get_piece(payload.piece_name)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    auth = (piece or {}).get('auth')
    auths = auth if isinstance(auth, list) else [auth]
    oauth = next((a for a in auths if isinstance(a, dict) and a.get('type') == 'OAUTH2'), None)
    if not oauth:
        raise HTTPException(status_code=400, detail='This piece has no OAuth2 authentication')
    scope = payload.scope or ' '.join(oauth.get('scope') or [])
    state = secrets.token_urlsafe(16)
    from urllib.parse import urlencode
    query = {'response_type': 'code', 'client_id': payload.client_id, 'redirect_uri': payload.redirect_url, 'scope': scope, 'state': state,
             'access_type': 'offline', 'prompt': 'consent'}
    for key, value in (oauth.get('extra') or {}).items():
        query[key] = value
    url = oauth['authUrl'] + ('&' if '?' in oauth['authUrl'] else '?') + urlencode(query)
    return {'authorization_url': url, 'state': state, 'scope': scope, 'token_url': oauth.get('tokenUrl'), 'pkce': bool(oauth.get('pkce'))}


# ----------------------------------------------------------------------------- testing and runs
TERMINAL_RUN_STATES = {'SUCCEEDED', 'FAILED', 'TIMEOUT', 'INTERNAL_ERROR', 'QUOTA_EXCEEDED', 'MEMORY_LIMIT_EXCEEDED', 'CANCELED', 'PAUSED'}


@router.post('/apps/{app_id}/studio/steps/{step_name}/test')
async def studio_test_step(app_id: str, step_name: str, user: AuthenticatedUser = Depends(require_workflow_admin), wait_seconds: float = 120.0):
    """Run the draft up to and including one step against the trigger's sample data.

    The engine queues a TESTING run and streams progress to its own UI over a websocket; the
    Studio instead polls the run until it settles and returns that step's input, output and error.
    """
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        flow = await activepieces.get_flow(app.ap_flow_id)
        version_id = ((flow or {}).get('version') or {}).get('id')
        if not version_id:
            raise HTTPException(status_code=409, detail='The flow has no draft version')
        run = await activepieces.step_run(version_id, step_name) or {}
        run_id = run.get('id')
        deadline = time.monotonic() + max(5.0, min(wait_seconds, 300.0))
        while run_id and run.get('status') not in TERMINAL_RUN_STATES and time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            run = await activepieces.get_run(run_id) or run
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    step = ((run.get('steps') or {}).get(step_name)) or {}
    settled = run.get('status') in TERMINAL_RUN_STATES
    return {'step': step_name, 'run_id': run_id, 'status': run.get('status'), 'settled': settled,
            'success': settled and step.get('status') == 'SUCCEEDED',
            'input': step.get('input'), 'output': step.get('output'), 'error': step.get('errorMessage'),
            'duration_ms': run.get('duration'), 'failed_step': run.get('failedStepName')}


@router.get('/apps/{app_id}/studio/steps/{step_name}/sample')
async def studio_step_sample(app_id: str, step_name: str, kind: str = 'OUTPUT', user: AuthenticatedUser = Depends(require_workflow_admin)):
    """Sample data recorded for a step (trigger sample or last test output), for the data picker."""
    _require_enabled()
    app = _get_app(app_id, user)
    if kind not in ('INPUT', 'OUTPUT'):
        raise HTTPException(status_code=400, detail='kind must be INPUT or OUTPUT')
    try:
        flow = await activepieces.get_flow(app.ap_flow_id)
        version_id = ((flow or {}).get('version') or {}).get('id')
        if not version_id:
            raise HTTPException(status_code=409, detail='The flow has no draft version')
        payload = await activepieces.get_sample_data(app.ap_flow_id, version_id, step_name, kind)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    return {'step': step_name, 'kind': kind, 'payload': payload}


@router.get('/apps/{app_id}/runs/{run_id}')
async def studio_run(app_id: str, run_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        run = await activepieces.get_run(run_id)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    if run is None or run.get('flowId') != app.ap_flow_id:
        raise HTTPException(status_code=404, detail='Run not found for this app')
    steps = run.get('steps') or {}
    return {'id': run.get('id'), 'status': run.get('status'), 'created': run.get('created'), 'finish_time': run.get('finishTime'),
            'duration_ms': run.get('duration'), 'flow_version_id': run.get('flowVersionId'), 'failed_step': run.get('failedStepName'),
            'steps': [{'name': name, 'status': (v or {}).get('status'), 'type': (v or {}).get('type'), 'input': (v or {}).get('input'),
                       'output': (v or {}).get('output'), 'error': (v or {}).get('errorMessage'), 'duration_ms': (v or {}).get('duration')}
                      for name, v in steps.items() if isinstance(v, dict)]}


@router.post('/apps/{app_id}/runs/{run_id}/retry')
async def studio_retry_run(app_id: str, run_id: str, strategy: str = 'ON_LATEST_VERSION', user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    if strategy not in ('ON_LATEST_VERSION', 'FROM_FAILED_STEP'):
        raise HTTPException(status_code=400, detail='strategy must be ON_LATEST_VERSION or FROM_FAILED_STEP')
    try:
        run = await activepieces.get_run(run_id)
        if run is None or run.get('flowId') != app.ap_flow_id:
            raise HTTPException(status_code=404, detail='Run not found for this app')
        result = await activepieces.retry_run(run_id, strategy)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    record_admin_event('workflow_studio_retry', user.email or user.user_id, {'app_id': app_id, 'run_id': run_id, 'strategy': strategy})
    return {'id': result.get('id'), 'status': result.get('status')}
