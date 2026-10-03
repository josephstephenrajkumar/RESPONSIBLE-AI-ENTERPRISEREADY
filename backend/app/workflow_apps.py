"""Workflow Apps: the gateway-side control plane for Activepieces.

Responsibilities (docs/ACTIVEPIECES_INTEGRATION.md, section 5.2):
  * bootstrap the engine: service-account session, custom piece archives, the
    LiteLLM-backed AI provider used by the universal AI pieces;
  * the app registry (`workflow_apps`) with per-app credentials: a LiteLLM virtual
    key (budget, attribution) and a gateway app token, both held by Activepieces as
    encrypted connections and stored here only as hashes;
  * create / publish / enable / disable / delete apps, list runs, proxy a chat turn;
  * ingest proxy spend for workflow keys into `llm_usage_events` so FinOps and AIOps
    see calls that bypass the gateway by design.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, String, Text

from app import workflow_templates as templates
from app import workflow_tokens
from app.activepieces_client import ActivepiecesError, activepieces
from app.auth import AuthenticatedUser, require_workflow_admin
from app.config import Settings
from app.database import Base, LLMUsageEventRecord, SessionLocal, append_llm_usage_event, engine
from app import gateway_settings
from app.litellm_admin import LiteLLMAdminError, litellm_admin, record_admin_event

logger = logging.getLogger('workflow_apps')
router = APIRouter(prefix='/workflows', tags=['workflow-apps'])

PLATFORM_KEY_ALIAS = 'workflow-apps-platform'
AI_PROVIDER_NAME = 'LiteLLM Proxy (Responsible AI)'
APP_STATUSES = ('draft', 'published', 'disabled')


# ----------------------------------------------------------------------------- tables
class WorkflowApp(Base):
    __tablename__ = 'workflow_apps'

    id = Column(String(40), primary_key=True)
    tenant_id = Column(String(160), nullable=False, default='default', index=True)
    owner_user_id = Column(String(160), nullable=False, default='')
    owner_email = Column(String(320), nullable=False, default='')
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default='')
    template = Column(String(40), nullable=False, default='responsible-ai-chat')
    rai_mode = Column(String(20), nullable=False, default='framework')
    model = Column(String(160), nullable=False, default='')
    ap_flow_id = Column(String(80), nullable=False, default='', index=True)
    ap_project_id = Column(String(80), nullable=False, default='')
    ap_connection_gateway = Column(String(120), nullable=False, default='')
    ap_connection_gateway_id = Column(String(80), nullable=False, default='')
    ap_connection_litellm = Column(String(120), nullable=False, default='')
    ap_connection_litellm_id = Column(String(80), nullable=False, default='')
    litellm_key_alias = Column(String(120), nullable=False, default='')
    litellm_key_hash = Column(String(128), nullable=False, default='')
    monthly_budget_usd = Column(Float, nullable=False, default=0.0)
    status = Column(String(20), nullable=False, default='draft')
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkflowSetting(Base):
    """Small key/value store for platform-level state (AI provider id, platform key hash)."""
    __tablename__ = 'workflow_settings'

    key = Column(String(80), primary_key=True)
    value = Column(Text, nullable=False, default='null')
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


def ensure_tables() -> None:
    WorkflowApp.__table__.create(bind=engine, checkfirst=True)
    WorkflowSetting.__table__.create(bind=engine, checkfirst=True)
    workflow_tokens.ensure_table()


def setting_get(key: str, default: Any = None) -> Any:
    with SessionLocal() as session:
        row = session.get(WorkflowSetting, key)
        if row is None:
            return default
        try:
            return json.loads(row.value)
        except json.JSONDecodeError:
            return default


def setting_set(key: str, value: Any) -> None:
    with SessionLocal() as session:
        row = session.get(WorkflowSetting, key)
        if row is None:
            session.add(WorkflowSetting(key=key, value=json.dumps(value)))
        else:
            row.value = json.dumps(value)
        session.commit()


_state: Dict[str, Any] = {'bootstrap_running': False, 'last_bootstrap': None, 'last_usage_sync': None}


# ----------------------------------------------------------------------------- schemas
class WorkflowAppCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    template: str = Field(default='responsible-ai-chat')
    rai_mode: str = Field(default='framework')
    model: str = Field(default='', max_length=160)
    monthly_budget_usd: float = Field(default=0.0, ge=0.0, le=100000.0)
    bot_name: str = Field(default='Responsible AI Bot', max_length=80)


class WorkflowAppStatusUpdate(BaseModel):
    enabled: bool


class WorkflowChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    session_id: str = Field(default='', max_length=120)


# ----------------------------------------------------------------------------- helpers
def _public_url() -> str:
    return Settings.ACTIVEPIECES_PUBLIC_URL.rstrip('/')


def serialize(app: WorkflowApp) -> Dict[str, Any]:
    return {
        'id': app.id, 'tenant_id': app.tenant_id, 'owner_user_id': app.owner_user_id, 'owner_email': app.owner_email,
        'name': app.name, 'description': app.description, 'template': app.template,
        'template_label': templates.TEMPLATES.get(app.template, {}).get('label', app.template),
        'rai_mode': app.rai_mode, 'model': app.model,
        'flow_id': app.ap_flow_id, 'project_id': app.ap_project_id,
        'connections': {'gateway': app.ap_connection_gateway, 'litellm': app.ap_connection_litellm},
        'litellm_key_alias': app.litellm_key_alias, 'monthly_budget_usd': app.monthly_budget_usd,
        'client_id': f'workflow-app:{app.id}', 'status': app.status,
        'published_at': app.published_at.isoformat() + 'Z' if app.published_at else None,
        'created_at': app.created_at.isoformat() + 'Z' if app.created_at else None,
        'builder_url': f'{_public_url()}/flows/{app.ap_flow_id}' if app.ap_flow_id else '',
        'chat_url': f'{_public_url()}/chats/{app.ap_flow_id}' if app.ap_flow_id else '',
    }


def _key_hash(created: Dict[str, Any]) -> str:
    """LiteLLM stores keys hashed (sha256 of the plaintext); `/key/generate` returns the hash as `token`."""
    token = created.get('token') or created.get('token_id')
    if token:
        return str(token)
    key = created.get('key', '')
    return hashlib.sha256(key.encode('utf-8')).hexdigest() if key else ''


def _ap_error(exc: ActivepiecesError) -> HTTPException:
    status = exc.status_code if 400 <= exc.status_code < 600 else 502
    return HTTPException(status_code=status, detail=f'Activepieces: {exc.detail}')


def _litellm_error(exc: LiteLLMAdminError) -> HTTPException:
    return HTTPException(status_code=502, detail=f'LiteLLM: {exc.detail}')


def _require_enabled() -> None:
    if not Settings.ACTIVEPIECES_ENABLED:
        raise HTTPException(status_code=503, detail='Workflow engine is disabled (ACTIVEPIECES_ENABLED=false)')


def _get_app(app_id: str, user: AuthenticatedUser) -> WorkflowApp:
    with SessionLocal() as session:
        app = session.get(WorkflowApp, app_id)
        if app is None or app.tenant_id != user.tenant_id:
            raise HTTPException(status_code=404, detail='Workflow app not found')
        session.expunge(app)
        return app


def _save(app: WorkflowApp) -> WorkflowApp:
    with SessionLocal() as session:
        merged = session.merge(app)
        session.commit()
        session.refresh(merged)
        session.expunge(merged)
        return merged


def piece_archives() -> List[Dict[str, str]]:
    """Built archives in ACTIVEPIECES_PIECES_DIR: [{name, version, path}]."""
    out: List[Dict[str, str]] = []
    for manifest in sorted(glob.glob(os.path.join(Settings.ACTIVEPIECES_PIECES_DIR, '*', 'package.json'))):
        try:
            with open(manifest, encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        name, version = data.get('name', ''), data.get('version', '')
        if not name or not version:
            continue
        tgz = os.path.join(Settings.ACTIVEPIECES_PIECES_DIR, f"{name.lstrip('@').replace('/', '-')}-{version}.tgz")
        if os.path.exists(tgz):
            out.append({'name': name, 'version': version, 'path': tgz})
    return out


def provider_models() -> List[str]:
    models = [gateway_settings.effective_default_model()]
    try:
        judge = gateway_settings.effective_judge_model()
    except Exception:  # pragma: no cover - defensive
        judge = ''
    for item in [judge] + list(gateway_settings.effective_allowed_models() or []):
        if item and item not in models:
            models.append(item)
    return models


# ----------------------------------------------------------------------------- bootstrap
async def bootstrap(actor: str = 'system', force: bool = False) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        'enabled': Settings.ACTIVEPIECES_ENABLED, 'service_configured': bool(Settings.ACTIVEPIECES_SERVICE_PASSWORD),
        'engine_reachable': False, 'signed_in': False, 'project_id': None, 'pieces': {}, 'ai_provider': None,
        'errors': [], 'started_at': datetime.utcnow().isoformat() + 'Z',
    }
    if not Settings.ACTIVEPIECES_ENABLED:
        return result
    if _state['bootstrap_running']:
        result['errors'].append('bootstrap already running')
        return result
    _state['bootstrap_running'] = True
    try:
        result['engine_reachable'] = await activepieces.ping()
        if not result['engine_reachable']:
            result['errors'].append(f'engine unreachable at {Settings.ACTIVEPIECES_API_URL}')
            return result
        if not result['service_configured']:
            result['errors'].append('ACTIVEPIECES_SERVICE_PASSWORD is not configured')
            return result
        try:
            await activepieces.sign_in()
        except ActivepiecesError as exc:
            result['errors'].append(f'sign-in failed: {exc.detail}')
            return result
        result['signed_in'] = True
        result['project_id'] = activepieces.project_id

        # Custom pieces ------------------------------------------------------
        for archive in piece_archives():
            name, version = archive['name'], archive['version']
            try:
                existing = await activepieces.get_piece(name)
                if existing and existing.get('version') == version and not force:
                    result['pieces'][name] = {'version': version, 'state': 'present'}
                    continue
                installed = await activepieces.install_piece_archive(archive['path'], name, version)
                state = 'already_installed' if installed.get('already_installed') else 'installed'
                result['pieces'][name] = {'version': version, 'state': state}
                record_admin_event('workflow_piece_installed', actor, {'piece': name, 'version': version, 'state': state})
            except ActivepiecesError as exc:
                result['pieces'][name] = {'version': version, 'state': 'failed', 'error': str(exc.detail)[:500]}
                result['errors'].append(f'piece {name}: {str(exc.detail)[:300]}')
        forms = await activepieces.get_piece(templates.FORMS_PIECE)
        result['pieces'][templates.FORMS_PIECE] = {'version': forms.get('version') if forms else None, 'state': 'present' if forms else 'missing'}
        if not forms:
            result['errors'].append('official forms piece (Chat UI) is not in the catalogue yet; piece sync may still be running')

        # AI provider backed by the LiteLLM proxy -----------------------------
        try:
            # /ai-providers?projectId lists provider *types* enabled for a project; the platform's
            # configured providers (with their display names) come from /ai-providers/configs.
            configs = await activepieces.list_ai_provider_configs()
            existing = next((p for p in configs if isinstance(p, dict) and (p.get('displayName') or p.get('name')) == AI_PROVIDER_NAME), None)
            stored_id = setting_get('ai_provider_id')
            if existing is None and stored_id:
                # Created earlier (for example by another worker's startup); the listing did not
                # surface it, so update by the id we recorded instead of creating a duplicate.
                existing = {'id': stored_id, 'name': AI_PROVIDER_NAME, 'source': 'stored'}
            result['engine_ai_providers'] = [{'id': p.get('id'), 'name': p.get('displayName') or p.get('name'), 'provider': p.get('provider')} for p in configs if isinstance(p, dict)]
            if existing and not force:
                result['ai_provider'] = {'id': existing.get('id'), 'state': 'present', 'models': provider_models()}
            else:
                created = await litellm_admin.post('/key/generate', {
                    'key_alias': f'{PLATFORM_KEY_ALIAS}-{secrets.token_hex(3)}',
                    'max_budget': Settings.WORKFLOW_PLATFORM_BUDGET_USD, 'budget_duration': '30d',
                    'metadata': {'purpose': 'workflow-apps-platform', 'tags': ['workflow-apps', 'client_id:workflow-apps-platform']},
                }, actor)
                key = created.get('key', '')
                body = {
                    'displayName': AI_PROVIDER_NAME, 'provider': 'custom',
                    'config': {
                        'apiKeyHeader': 'Authorization', 'baseUrl': Settings.ACTIVEPIECES_LITELLM_URL,
                        'models': [{'modelId': m, 'modelName': f'{m} (LiteLLM)', 'modelType': 'text'} for m in provider_models()],
                        'defaultHeaders': {'x-litellm-tags': 'workflow-apps'},
                    },
                    'auth': {'apiKey': f'Bearer {key}'},
                }
                if existing:
                    provider = await activepieces.update_ai_provider(existing['id'], {k: body[k] for k in ('displayName', 'config', 'auth')})
                else:
                    try:
                        provider = await activepieces.create_ai_provider(body)
                    except ActivepiecesError as exc:
                        if exc.status_code != 409:
                            raise
                        # Name already taken on the engine: adopt it instead of failing.
                        again = next((p for p in await activepieces.list_ai_provider_configs() if isinstance(p, dict) and (p.get('displayName') or p.get('name')) == AI_PROVIDER_NAME), None)
                        if again is None:
                            raise
                        existing = again
                        provider = await activepieces.update_ai_provider(again['id'], {k: body[k] for k in ('displayName', 'config', 'auth')})
                setting_set('platform_key_hash', _key_hash(created))
                setting_set('platform_key_alias', created.get('key_alias') or PLATFORM_KEY_ALIAS)
                provider_id = (provider.get('id') if isinstance(provider, dict) else None) or (existing or {}).get('id')
                setting_set('ai_provider_id', provider_id)
                result['ai_provider'] = {'id': provider_id, 'state': 'updated' if existing else 'created', 'models': provider_models()}
                record_admin_event('workflow_ai_provider_configured', actor, {'provider': AI_PROVIDER_NAME, 'models': provider_models()})
        except (ActivepiecesError, LiteLLMAdminError) as exc:
            detail = getattr(exc, 'detail', str(exc))
            result['ai_provider'] = {'state': 'failed', 'error': str(detail)[:500]}
            result['errors'].append(f'ai provider: {str(detail)[:300]}')

        setting_set('bootstrapped_at', datetime.utcnow().isoformat() + 'Z')
        setting_set('pieces', result['pieces'])
        return result
    finally:
        _state['bootstrap_running'] = False
        result['finished_at'] = datetime.utcnow().isoformat() + 'Z'
        _state['last_bootstrap'] = result


async def startup() -> None:
    """Called from the FastAPI startup hook: bootstrap, then periodic usage sync."""
    if not Settings.ACTIVEPIECES_ENABLED:
        return
    if Settings.WORKFLOW_BOOTSTRAP_ON_STARTUP:
        try:
            await bootstrap('startup')
        except Exception as exc:  # pragma: no cover - never let startup die
            logger.warning('workflow bootstrap failed: %s', exc)
    while True:
        await asyncio.sleep(max(30, Settings.WORKFLOW_USAGE_SYNC_SECONDS))
        try:
            await usage_sync('scheduler')
        except Exception as exc:  # pragma: no cover
            logger.warning('workflow usage sync failed: %s', exc)


# ----------------------------------------------------------------------------- usage ingestion
def spend_row_to_event(row: Dict[str, Any], app: Optional[WorkflowApp], client_id: str, tenant_id: str) -> Dict[str, Any]:
    """Map one LiteLLM spend-log row onto an llm_usage_events row."""
    start, end = row.get('startTime'), row.get('endTime')
    latency_ms = 0
    try:
        if start and end:
            s = datetime.fromisoformat(str(start).replace('Z', '+00:00'))
            e = datetime.fromisoformat(str(end).replace('Z', '+00:00'))
            latency_ms = max(0, int((e - s).total_seconds() * 1000))
    except ValueError:
        pass
    metadata = row.get('metadata') or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    model = str(row.get('model') or '')
    provider = str(row.get('custom_llm_provider') or metadata.get('custom_llm_provider') or (model.split('/')[0] if '/' in model else ''))
    status = str(row.get('status') or 'success').lower()
    return {
        'request_id': str(row.get('request_id') or ''), 'call_id': str(row.get('request_id') or ''),
        'timestamp': start or datetime.utcnow().isoformat(),
        'user_id': str(row.get('user') or row.get('end_user') or client_id),
        'user_email': '', 'tenant_id': tenant_id, 'client_id': client_id,
        'agent_id': client_id if app else 'workflow-apps-platform', 'session_id': str(row.get('end_user') or ''),
        'mode': 'workflow', 'purpose': 'workflow',
        'requested_model': model, 'served_model': model, 'provider': provider, 'gateway_mode': 'proxy-direct',
        'api_base': str(row.get('api_base') or ''),
        'prompt_tokens': int(row.get('prompt_tokens') or 0), 'completion_tokens': int(row.get('completion_tokens') or 0),
        'total_tokens': int(row.get('total_tokens') or 0), 'cost_usd': float(row.get('spend') or 0.0), 'cost_source': 'litellm',
        'latency_ms': latency_ms, 'retries': 0, 'fallbacks': 0,
        'status': 'error' if status in ('failure', 'failed', 'error') else 'success', 'error_type': '',
    }


async def usage_sync(actor: str = 'manual') -> Dict[str, Any]:
    """Pull proxy spend for every workflow key into llm_usage_events (idempotent on call_id)."""
    result: Dict[str, Any] = {'started_at': datetime.utcnow().isoformat() + 'Z', 'keys': 0, 'rows_seen': 0, 'inserted': 0, 'errors': []}
    with SessionLocal() as session:
        apps = session.query(WorkflowApp).filter(WorkflowApp.litellm_key_hash != '').all()
        for app in apps:
            session.expunge(app)
        existing = {row[0] for row in session.query(LLMUsageEventRecord.call_id).filter(LLMUsageEventRecord.purpose == 'workflow').all() if row[0]}
    targets: List[Dict[str, Any]] = [{'hash': a.litellm_key_hash, 'app': a, 'client_id': f'workflow-app:{a.id}', 'tenant_id': a.tenant_id} for a in apps]
    platform_hash = setting_get('platform_key_hash')
    if platform_hash:
        targets.append({'hash': platform_hash, 'app': None, 'client_id': 'workflow-apps-platform', 'tenant_id': 'platform'})
    for target in targets:
        result['keys'] += 1
        try:
            rows = await litellm_admin.get('/spend/logs', api_key=target['hash'])
        except LiteLLMAdminError as exc:
            result['errors'].append(f"{target['client_id']}: {str(exc.detail)[:200]}")
            continue
        if isinstance(rows, dict):
            rows = rows.get('data') or rows.get('logs') or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            result['rows_seen'] += 1
            call_id = str(row.get('request_id') or '')
            if not call_id or call_id in existing:
                continue
            try:
                append_llm_usage_event(spend_row_to_event(row, target['app'], target['client_id'], target['tenant_id']))
                existing.add(call_id)
                result['inserted'] += 1
            except Exception as exc:  # pragma: no cover - keep syncing other rows
                result['errors'].append(f'{call_id}: {exc}')
    result['finished_at'] = datetime.utcnow().isoformat() + 'Z'
    _state['last_usage_sync'] = result
    setting_set('usage_sync_last', {k: v for k, v in result.items() if k != 'errors'} | {'error_count': len(result['errors'])})
    return result


# ----------------------------------------------------------------------------- app lifecycle
async def resolve_piece_versions() -> Dict[str, str]:
    versions: Dict[str, str] = {}
    missing: List[str] = []
    for name in (templates.FORMS_PIECE, templates.GATEWAY_PIECE, templates.LITELLM_PIECE):
        piece = await activepieces.get_piece(name)
        if piece and piece.get('version'):
            versions[name] = str(piece['version'])
        else:
            missing.append(name)
    if missing:
        raise HTTPException(status_code=503, detail=f"Pieces missing from the engine catalogue: {', '.join(missing)}. Run bootstrap first.")
    return versions


async def create_app(payload: WorkflowAppCreate, user: AuthenticatedUser) -> Dict[str, Any]:
    if payload.template not in templates.TEMPLATES:
        raise HTTPException(status_code=400, detail=f'Unknown template {payload.template!r}')
    if payload.rai_mode not in ('framework', 'code'):
        raise HTTPException(status_code=400, detail='rai_mode must be framework or code')
    model = payload.model.strip() or gateway_settings.effective_default_model()
    budget = payload.monthly_budget_usd or Settings.WORKFLOW_DEFAULT_BUDGET_USD
    actor = user.email or user.user_id
    try:
        versions = await resolve_piece_versions()
    except ActivepiecesError as exc:
        raise _ap_error(exc)

    app_id = 'wf_' + secrets.token_hex(5)
    tenant = user.tenant_id
    cleanup: List[Any] = []
    try:
        # 1. LiteLLM virtual key: budget + attribution tags; only its hash is kept here.
        try:
            created = await litellm_admin.post('/key/generate', {
                'key_alias': f'wfapp-{app_id}', 'max_budget': budget, 'budget_duration': '30d',
                'metadata': {'workflow_app_id': app_id, 'tenant_id': tenant, 'created_by': actor,
                             'tags': ['workflow-apps', f'client_id:workflow-app:{app_id}', f'tenant:{tenant}']},
            }, actor)
        except LiteLLMAdminError as exc:
            raise _litellm_error(exc)
        litellm_key = created.get('key', '')
        if not litellm_key:
            raise HTTPException(status_code=502, detail='LiteLLM did not return a key')
        cleanup.append(('key', litellm_key))

        # 2. gateway app token (plaintext goes to Activepieces only)
        app_token = workflow_tokens.issue_token(app_id, tenant)
        cleanup.append(('token', app_id))

        # 3. connections held encrypted by Activepieces
        ext_gateway, ext_litellm = f'{app_id}-gateway', f'{app_id}-litellm'
        conn_gateway = await activepieces.upsert_custom_auth_connection(
            ext_gateway, f'{payload.name} · gateway', templates.GATEWAY_PIECE,
            {'gatewayUrl': Settings.ACTIVEPIECES_GATEWAY_URL, 'appToken': app_token})
        cleanup.append(('connection', conn_gateway.get('id')))
        conn_litellm = await activepieces.upsert_custom_auth_connection(
            ext_litellm, f'{payload.name} · LiteLLM key', templates.LITELLM_PIECE,
            {'proxyUrl': Settings.ACTIVEPIECES_LITELLM_URL, 'apiKey': litellm_key})
        cleanup.append(('connection', conn_litellm.get('id')))

        # 4. flow from template
        flow = await activepieces.create_flow(payload.name, app_id, {'responsible_ai': {'app_id': app_id, 'tenant_id': tenant, 'template': payload.template}})
        flow_id = flow['id']
        cleanup.append(('flow', flow_id))
        trigger = templates.build_trigger(
            payload.template, versions=versions, connection_gateway=ext_gateway, connection_litellm=ext_litellm,
            app_id=app_id, bot_name=payload.bot_name, rai_mode=payload.rai_mode, model=model)
        await activepieces.import_flow(flow_id, payload.name, trigger)
    except ActivepiecesError as exc:
        await _cleanup(cleanup, actor)
        raise _ap_error(exc)
    except HTTPException:
        await _cleanup(cleanup, actor)
        raise

    app = WorkflowApp(
        id=app_id, tenant_id=tenant, owner_user_id=user.user_id, owner_email=user.email,
        name=payload.name, description=payload.description, template=payload.template, rai_mode=payload.rai_mode, model=model,
        ap_flow_id=flow_id, ap_project_id=activepieces.project_id or '',
        ap_connection_gateway=ext_gateway, ap_connection_gateway_id=str(conn_gateway.get('id') or ''),
        ap_connection_litellm=ext_litellm, ap_connection_litellm_id=str(conn_litellm.get('id') or ''),
        litellm_key_alias=f'wfapp-{app_id}', litellm_key_hash=_key_hash(created), monthly_budget_usd=budget, status='draft',
    )
    app = _save(app)
    record_admin_event('workflow_app_created', actor, {'app_id': app_id, 'template': payload.template, 'flow_id': flow_id, 'tenant_id': tenant})
    return serialize(app)


async def _cleanup(items: List[Any], actor: str) -> None:
    for kind, value in reversed(items):
        try:
            if kind == 'key' and value:
                await litellm_admin.post('/key/delete', {'keys': [value]}, actor)
            elif kind == 'token':
                workflow_tokens.revoke_tokens(value)
            elif kind == 'connection' and value:
                await activepieces.delete_connection(str(value))
            elif kind == 'flow' and value:
                await activepieces.delete_flow(str(value))
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning('cleanup %s %s failed: %s', kind, value, exc)


async def delete_app(app: WorkflowApp, actor: str) -> None:
    errors: List[str] = []
    try:
        await activepieces.delete_flow(app.ap_flow_id)
    except ActivepiecesError as exc:
        errors.append(f'flow: {exc.detail}')
    for conn_id in (app.ap_connection_gateway_id, app.ap_connection_litellm_id):
        if conn_id:
            try:
                await activepieces.delete_connection(conn_id)
            except ActivepiecesError as exc:
                errors.append(f'connection {conn_id}: {exc.detail}')
    if app.litellm_key_hash:
        try:
            await litellm_admin.post('/key/delete', {'keys': [app.litellm_key_hash]}, actor)
        except LiteLLMAdminError as exc:
            errors.append(f'key: {exc.detail}')
    workflow_tokens.revoke_tokens(app.id)
    with SessionLocal() as session:
        row = session.get(WorkflowApp, app.id)
        if row is not None:
            session.delete(row)
            session.commit()
    record_admin_event('workflow_app_deleted', actor, {'app_id': app.id, 'errors': errors})
    if errors:
        logger.warning('workflow app %s deleted with cleanup errors: %s', app.id, errors)


# ----------------------------------------------------------------------------- routes
async def _engine_ai_providers() -> list:
    try:
        configs = await activepieces.list_ai_provider_configs()
    except ActivepiecesError as exc:
        return [{'error': f'{exc.status_code}: {str(exc.detail)[:160]}'}]
    return [{'id': p.get('id'), 'name': p.get('displayName') or p.get('name'), 'provider': p.get('provider')} for p in configs if isinstance(p, dict)]


@router.get('/status')
async def workflow_status(user: AuthenticatedUser = Depends(require_workflow_admin)):
    reachable = await activepieces.ping() if Settings.ACTIVEPIECES_ENABLED else False
    return {
        'enabled': Settings.ACTIVEPIECES_ENABLED,
        'service_configured': bool(Settings.ACTIVEPIECES_SERVICE_PASSWORD),
        'service_email': Settings.ACTIVEPIECES_SERVICE_EMAIL,
        'api_url': Settings.ACTIVEPIECES_API_URL, 'public_url': _public_url(),
        'gateway_url_for_engine': Settings.ACTIVEPIECES_GATEWAY_URL, 'litellm_url_for_engine': Settings.ACTIVEPIECES_LITELLM_URL,
        'engine_reachable': reachable, 'signed_in': activepieces.signed_in, 'project_id': activepieces.project_id,
        'bootstrapped_at': setting_get('bootstrapped_at'), 'pieces': setting_get('pieces', {}),
        'ai_provider_id': setting_get('ai_provider_id'), 'ai_provider_name': AI_PROVIDER_NAME,
        'engine_ai_providers': await _engine_ai_providers() if reachable else [],
        'last_bootstrap': _state['last_bootstrap'], 'last_usage_sync': _state['last_usage_sync'] or setting_get('usage_sync_last'),
        'archives': [{'name': a['name'], 'version': a['version']} for a in piece_archives()],
        'templates': [{'id': k, **v} for k, v in templates.TEMPLATES.items()],
        'edition_notes': 'Community edition: builder needs an Activepieces login; embedding SSO, API keys and per-project piece governance need the enterprise licence.',
    }


@router.post('/bootstrap')
async def workflow_bootstrap(force: bool = False, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    return await bootstrap(user.email or user.user_id, force=force)


@router.get('/apps')
def list_apps(user: AuthenticatedUser = Depends(require_workflow_admin)):
    with SessionLocal() as session:
        rows = session.query(WorkflowApp).filter(WorkflowApp.tenant_id == user.tenant_id).order_by(WorkflowApp.created_at.desc()).all()
        return {'apps': [serialize(row) for row in rows]}


@router.post('/apps', status_code=201)
async def create_app_route(payload: WorkflowAppCreate, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    return await create_app(payload, user)


@router.get('/apps/{app_id}')
def get_app(app_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    return serialize(_get_app(app_id, user))


@router.post('/apps/{app_id}/publish')
async def publish_app(app_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        flow = await activepieces.publish_flow(app.ap_flow_id)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    app.status = 'published' if flow.get('status', 'ENABLED') == 'ENABLED' else 'disabled'
    app.published_at = datetime.utcnow()
    app = _save(app)
    record_admin_event('workflow_app_published', user.email or user.user_id, {'app_id': app_id, 'flow_id': app.ap_flow_id, 'published_version_id': flow.get('publishedVersionId')})
    return serialize(app)


@router.post('/apps/{app_id}/status')
async def set_app_status(app_id: str, payload: WorkflowAppStatusUpdate, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    if not app.published_at and payload.enabled:
        raise HTTPException(status_code=409, detail='Publish the app before enabling it')
    try:
        await activepieces.set_flow_status(app.ap_flow_id, payload.enabled)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    app.status = 'published' if payload.enabled else 'disabled'
    app = _save(app)
    record_admin_event('workflow_app_status', user.email or user.user_id, {'app_id': app_id, 'enabled': payload.enabled})
    return serialize(app)


@router.delete('/apps/{app_id}')
async def delete_app_route(app_id: str, user: AuthenticatedUser = Depends(require_workflow_admin)):
    app = _get_app(app_id, user)
    await delete_app(app, user.email or user.user_id)
    return {'deleted': app_id}


@router.get('/apps/{app_id}/runs')
async def app_runs(app_id: str, limit: int = 20, user: AuthenticatedUser = Depends(require_workflow_admin)):
    _require_enabled()
    app = _get_app(app_id, user)
    try:
        runs = await activepieces.list_runs(app.ap_flow_id, limit=max(1, min(limit, 100)))
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    return {'runs': [{'id': r.get('id'), 'status': r.get('status'), 'created': r.get('created'), 'finish_time': r.get('finishTime'),
                      'duration_ms': r.get('duration'), 'environment': r.get('environment')} for r in runs if isinstance(r, dict)]}


@router.post('/apps/{app_id}/chat')
async def app_chat(app_id: str, payload: WorkflowChatRequest, user: AuthenticatedUser = Depends(require_workflow_admin)):
    """Send one chat turn to the app's published flow through the gateway (Cognito-protected)."""
    _require_enabled()
    app = _get_app(app_id, user)
    if app.status != 'published':
        raise HTTPException(status_code=409, detail='The app is not published')
    session_id = payload.session_id or f'gateway-{user.user_id}-{app_id}'
    started = time.time()
    try:
        status, body = await activepieces.chat(app.ap_flow_id, session_id, payload.message)
    except ActivepiecesError as exc:
        raise _ap_error(exc)
    if status != 200:
        raise HTTPException(status_code=502, detail={'engine_status': status, 'body': body})
    answer = body.get('value') if isinstance(body, dict) else body
    return {'app_id': app_id, 'session_id': session_id, 'answer': answer, 'type': body.get('type') if isinstance(body, dict) else None,
            'latency_ms': int((time.time() - started) * 1000), 'raw': body}


@router.post('/usage/sync')
async def usage_sync_route(user: AuthenticatedUser = Depends(require_workflow_admin)):
    return await usage_sync(user.email or user.user_id)
