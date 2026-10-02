"""Runtime settings an administrator can change without a redeploy.

Stored in the application database (table `gateway_settings`) and layered over the
environment defaults in `Settings`. Used by the Proxy Manager screen for:

    providers.disabled   providers hidden from the catalogue and rejected by /chat
    models.disabled      model names hidden from the chat selector and rejected by /chat
    chat.default_model   overrides LLM_DEFAULT_MODEL
    chat.judge_model     overrides LLM_JUDGE_MODEL (Ragas/TruLens judges)
    chat.allowed_models  overrides LLM_ALLOWED_MODELS (empty list = inherit env)

Every change is written to the policy audit trail with the actor.
"""

import hashlib
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, String, Text

from app.config import Settings
from app.database import Base, PolicyAuditEvent, SessionLocal, engine

KNOWN_KEYS = {
    'providers.disabled': list,
    'models.disabled': list,
    'chat.default_model': str,
    'chat.judge_model': str,
    'chat.allowed_models': list,
}

_CACHE_TTL_SECONDS = 15
_cache: Dict[str, Any] = {'loaded_at': 0.0, 'values': {}}


class GatewaySetting(Base):
    __tablename__ = 'gateway_settings'

    key = Column(String(120), primary_key=True)
    value = Column(Text, nullable=False, default='null')
    updated_by = Column(String(160), nullable=False, default='system')
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


def ensure_table() -> None:
    GatewaySetting.__table__.create(bind=engine, checkfirst=True)


def _load(force: bool = False) -> Dict[str, Any]:
    if not force and time.time() - _cache['loaded_at'] < _CACHE_TTL_SECONDS:
        return _cache['values']
    values: Dict[str, Any] = {}
    try:
        with SessionLocal() as session:
            for row in session.query(GatewaySetting).all():
                try:
                    values[row.key] = json.loads(row.value)
                except json.JSONDecodeError:
                    continue
    except Exception:
        values = dict(_cache['values'])
    _cache['values'] = values
    _cache['loaded_at'] = time.time()
    return values


def invalidate_cache() -> None:
    _cache['loaded_at'] = 0.0


def raw_settings() -> Dict[str, Any]:
    return dict(_load())


def get(key: str, default: Any = None) -> Any:
    return _load().get(key, default)


def set_value(key: str, value: Any, actor: str) -> Dict[str, Any]:
    if key not in KNOWN_KEYS:
        raise ValueError(f'Unknown setting {key!r}')
    expected = KNOWN_KEYS[key]
    if value is not None and not isinstance(value, expected):
        raise ValueError(f'{key} must be a {expected.__name__}')
    if expected is list and value is not None:
        value = sorted({str(item).strip() for item in value if str(item).strip()})
    if expected is str and value is not None:
        value = value.strip() or None
    previous = get(key)
    with SessionLocal() as session:
        row = session.get(GatewaySetting, key)
        if row is None:
            row = GatewaySetting(key=key)
            session.add(row)
        row.value = json.dumps(value)
        row.updated_by = actor or 'system'
        row.updated_at = datetime.utcnow()
        session.add(PolicyAuditEvent(
            policy_id=None, action='setting_changed', actor=actor or 'system',
            event_hash=hashlib.sha256(json.dumps({'key': key, 'value': value, 'actor': actor}, sort_keys=True, default=str).encode()).hexdigest(),
            details=json.dumps({'key': key, 'previous': previous, 'value': value}, default=str),
            created_at=datetime.utcnow(),
        ))
        session.commit()
    invalidate_cache()
    return {'key': key, 'value': value, 'previous': previous}


# ----------------------------------------------------------------------------
# Effective values (DB override -> environment default)
# ----------------------------------------------------------------------------
def effective_default_model() -> str:
    return get('chat.default_model') or Settings.LLM_DEFAULT_MODEL


def effective_judge_model() -> str:
    return get('chat.judge_model') or Settings.LLM_JUDGE_MODEL


def effective_allowed_models() -> List[str]:
    override = get('chat.allowed_models')
    return list(override) if override else list(Settings.LLM_ALLOWED_MODELS)


def disabled_providers() -> List[str]:
    return list(get('providers.disabled') or [])


def disabled_models() -> List[str]:
    return list(get('models.disabled') or [])


def effective_view() -> Dict[str, Any]:
    return {
        'default_model': effective_default_model(),
        'judge_model': effective_judge_model(),
        'allowed_models': effective_allowed_models(),
        'disabled_providers': disabled_providers(),
        'disabled_models': disabled_models(),
        'env_defaults': {
            'default_model': Settings.LLM_DEFAULT_MODEL,
            'judge_model': Settings.LLM_JUDGE_MODEL,
            'allowed_models': Settings.LLM_ALLOWED_MODELS,
            'providers_enabled': Settings.LLM_PROVIDERS_ENABLED,
        },
        'overrides': raw_settings(),
    }
