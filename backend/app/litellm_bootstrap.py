"""Seed and read the LiteLLM proxy's DB-managed runtime settings.

`litellm/config.yaml` is deliberately a bootstrap-only file (models, keys, database,
platform observability). Everything an administrator should be able to change at
runtime — router settings (retries, timeouts, cooldown, fallbacks), litellm settings
(drop_params, request_timeout, success/failure callbacks), general settings, cache
parameters — is stored by LiteLLM in its database through `POST /config/update` and
merged into the running config (`store_model_in_db: true`). LiteLLM refuses runtime
updates to keys pinned in the file, which is why they are not pinned there.

`litellm_runtime_defaults.json` (shipped in this image, reviewed in Git) is applied
once, at start-up, when the proxy has no router settings yet; afterwards the Proxy
Manager owns the values.
"""

import json
import logging
import pathlib
from typing import Any, Dict, Optional

from app.litellm_admin import LiteLLMAdminError, litellm_admin, record_admin_event

log = logging.getLogger(__name__)

DEFAULTS_PATH = pathlib.Path(__file__).with_name('litellm_runtime_defaults.json')

# Router keys the UI edits; everything else LiteLLM reports is shown read-only.
EDITABLE_ROUTER_KEYS = ['num_retries', 'timeout', 'allowed_fails', 'cooldown_time', 'routing_strategy', 'fallbacks',
                        'context_window_fallbacks', 'retry_after', 'enable_tag_filtering']
EDITABLE_LITELLM_KEYS = ['drop_params', 'request_timeout', 'success_callback', 'failure_callback', 'max_budget', 'budget_duration']


def load_defaults() -> Dict[str, Any]:
    try:
        data = json.loads(DEFAULTS_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    data.pop('_comment', None)
    return data


def _router_settings_from(callbacks_payload: Any) -> Dict[str, Any]:
    if isinstance(callbacks_payload, dict):
        return callbacks_payload.get('router_settings') or {}
    return {}


async def current_config() -> Dict[str, Any]:
    """Merged view for the Routing & Settings screen."""
    callbacks = await litellm_admin.safe_get('/get/config/callbacks')
    settings = await litellm_admin.safe_get('/settings')
    general_fields = await litellm_admin.safe_get('/config/list', config_type='general_settings')
    cache = await litellm_admin.safe_get('/cache/settings')
    cache_ping = await litellm_admin.safe_get('/cache/ping')
    router = _router_settings_from(callbacks)
    live_litellm = {}
    if isinstance(settings, dict):
        for key, value in settings.items():
            # Only scalar settings are useful to an administrator; LiteLLM also lists
            # its internal callback objects here, which are noise.
            scalar = isinstance(value, (str, int, float, bool)) or value is None
            if isinstance(key, str) and key.startswith('litellm.') and scalar:
                live_litellm[key[len('litellm.'):]] = value
    return {
        'defaults': load_defaults(),
        'seeded': bool(router.get('fallbacks')) or bool(router.get('cooldown_time') not in (None, 5)),
        'router_settings': router,
        'editable_router_keys': EDITABLE_ROUTER_KEYS,
        'editable_litellm_keys': EDITABLE_LITELLM_KEYS,
        'litellm_settings_live': live_litellm,
        'callbacks': callbacks.get('callbacks') if isinstance(callbacks, dict) else [],
        'available_callbacks': callbacks.get('available_callbacks') if isinstance(callbacks, dict) else [],
        'alerts': callbacks.get('alerts') if isinstance(callbacks, dict) else [],
        'general_settings_fields': general_fields if isinstance(general_fields, list) else [],
        'cache': cache if isinstance(cache, dict) else {'fields': [], 'current_values': {}},
        'cache_ping': cache_ping,
        'pinned_in_config_yaml': ['model_list', 'litellm_settings.set_verbose', 'litellm_settings.return_response_headers',
                                  'litellm_settings.callbacks', 'general_settings.master_key', 'general_settings.database_url',
                                  'general_settings.store_model_in_db', 'general_settings.allow_requests_on_db_unavailable'],
    }


async def ensure_runtime_defaults(actor: str = 'gateway-startup', force: bool = False) -> Dict[str, Any]:
    """Apply the shipped defaults when the proxy has none (idempotent)."""
    defaults = load_defaults()
    if not defaults:
        return {'applied': False, 'reason': 'no defaults file'}
    try:
        callbacks = await litellm_admin.get('/get/config/callbacks')
    except LiteLLMAdminError as exc:
        return {'applied': False, 'reason': f'proxy unavailable: {exc.detail}'}
    router = _router_settings_from(callbacks)
    already = bool(router.get('fallbacks'))
    if already and not force:
        return {'applied': False, 'reason': 'router settings already present', 'router_settings': router}
    payload = {k: v for k, v in defaults.items() if k in ('router_settings', 'litellm_settings', 'general_settings') and v}
    try:
        result = await litellm_admin.post('/config/update', payload, actor=actor)
    except LiteLLMAdminError as exc:
        return {'applied': False, 'reason': f'config update rejected: {exc.detail}'}
    record_admin_event('litellm_runtime_defaults_seeded', actor, {'keys': {k: list(v.keys()) for k, v in payload.items()}})
    return {'applied': True, 'litellm_response': result, 'payload': payload}


async def startup_seed() -> None:
    try:
        result = await ensure_runtime_defaults()
        log.info('litellm runtime defaults: %s', result.get('reason') or ('applied' if result.get('applied') else result))
    except Exception as exc:  # never block start-up
        log.warning('litellm runtime defaults seeding skipped: %s', exc)
