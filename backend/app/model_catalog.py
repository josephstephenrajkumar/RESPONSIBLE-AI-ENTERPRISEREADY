"""Provider and model catalogue for the admin screen, backed by the LiteLLM proxy.

LiteLLM exposes everything this module needs (see docs/MODEL_CATALOG.md):

    GET  /model/info                      deployments the key can use, with provider, costs, limits
    GET  /model_group/info                model groups (chat-default, judge-fast, ...)
    GET  /public/litellm_model_cost_map   every model LiteLLM knows how to price, by provider
    POST /model/new                       add a deployment at runtime (persisted when store_model_in_db=true)
    POST /model/delete                    remove a runtime-added deployment
    GET  /health?model=<name>             provider-side health check for one deployment

The gateway adds the governance layer: a fixed registry of providers, "enabled" status driven by
which credentials the *proxy* holds (LLM_PROVIDERS_ENABLED), explicit model enablement (no wildcard
routes), and a refusal to accept raw provider keys from the UI - new models reference
`os.environ/<KEY>` so the credential boundary (keys only in the proxy task) holds.
"""

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app import gateway_settings
from app.config import Settings
from app.database import PolicyAuditEvent, SessionLocal

# ----------------------------------------------------------------------------
# Provider registry. `prefix` is the LiteLLM provider route; `cost_map_providers`
# are the `litellm_provider` values used in LiteLLM's price map.
# ----------------------------------------------------------------------------
PROVIDERS: Dict[str, Dict[str, Any]] = {
    'groq': {
        'display_name': 'Groq',
        'prefix': 'groq',
        'credential': {'type': 'api_key', 'env': 'GROQ_API_KEY', 'secret': 'groq_api_key'},
        'cost_map_providers': ['groq'],
        'discovery': 'cost_map',
        'docs': 'https://console.groq.com/docs/models',
    },
    'bedrock': {
        'display_name': 'Amazon Bedrock',
        'prefix': 'bedrock',
        'credential': {'type': 'iam', 'note': 'proxy task role (bedrock:InvokeModel); no API key'},
        'cost_map_providers': ['bedrock', 'bedrock_converse'],
        'discovery': 'bedrock',
        'docs': 'https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html',
    },
    'anthropic': {
        'display_name': 'Anthropic',
        'prefix': 'anthropic',
        'credential': {'type': 'api_key', 'env': 'ANTHROPIC_API_KEY', 'secret': 'anthropic_api_key'},
        'cost_map_providers': ['anthropic'],
        'discovery': 'cost_map',
        'docs': 'https://docs.anthropic.com/en/docs/about-claude/models',
    },
    'openai': {
        'display_name': 'OpenAI',
        'prefix': 'openai',
        'credential': {'type': 'api_key', 'env': 'OPENAI_API_KEY', 'secret': 'openai_api_key'},
        'cost_map_providers': ['openai'],
        'discovery': 'cost_map',
        'docs': 'https://platform.openai.com/docs/models',
    },
    'gemini': {
        'display_name': 'Google Gemini',
        'prefix': 'gemini',
        'credential': {'type': 'api_key', 'env': 'GEMINI_API_KEY', 'secret': 'gemini_api_key'},
        'cost_map_providers': ['gemini'],
        'discovery': 'cost_map',
        'docs': 'https://ai.google.dev/gemini-api/docs/models',
    },
    'mistral': {
        'display_name': 'Mistral AI',
        'prefix': 'mistral',
        'credential': {'type': 'api_key', 'env': 'MISTRAL_API_KEY', 'secret': 'mistral_api_key'},
        'cost_map_providers': ['mistral'],
        'discovery': 'cost_map',
        'docs': 'https://docs.mistral.ai/getting-started/models/',
    },
}

_MODEL_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/\-]{1,200}$')
_ALIAS_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,120}$')


def provider_for_litellm_model(litellm_model: str, litellm_provider: Optional[str] = None) -> str:
    """Map a LiteLLM deployment to a registry provider key."""
    if litellm_provider:
        for key, spec in PROVIDERS.items():
            if litellm_provider in spec['cost_map_providers'] or litellm_provider == spec['prefix']:
                return key
    head = (litellm_model or '').split('/', 1)[0]
    for key, spec in PROVIDERS.items():
        if head == spec['prefix']:
            return key
    return litellm_provider or head or 'unknown'


def _per_million(value: Any) -> Optional[float]:
    try:
        return round(float(value) * 1_000_000, 4) if value is not None else None
    except (TypeError, ValueError):
        return None


def _event_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def record_catalog_event(action: str, actor: str, details: Dict[str, Any]) -> None:
    """Catalogue changes are governance events; keep them in the policy audit trail."""
    try:
        with SessionLocal() as session:
            session.add(PolicyAuditEvent(
                policy_id=None,
                action=action,
                actor=actor or 'system',
                event_hash=_event_hash({'action': action, 'actor': actor, **details}),
                details=json.dumps(details, default=str),
                created_at=datetime.utcnow(),
            ))
            session.commit()
    except Exception:
        pass


class ModelCatalog:
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
        self._cost_map: Optional[Dict[str, Any]] = None
        self._cost_map_loaded_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Proxy access
    # ------------------------------------------------------------------
    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _admin_headers() -> Dict[str, str]:
        key = Settings.LITELLM_ADMIN_API_KEY or Settings.LITELLM_API_KEY
        headers = {'Content-Type': 'application/json'}
        if key:
            headers['Authorization'] = f'Bearer {key}'
        return headers

    @staticmethod
    def _base_url() -> str:
        return Settings.LITELLM_PROXY_URL

    async def _get(self, path: str, **kwargs) -> Any:
        response = await self._client_or_create().get(f'{self._base_url()}{path}', headers=self._admin_headers(), **kwargs)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        response = await self._client_or_create().post(f'{self._base_url()}{path}', headers=self._admin_headers(), json=payload)
        if response.status_code >= 400:
            try:
                detail = response.json()
                detail = detail.get('error', detail) if isinstance(detail, dict) else detail
            except Exception:
                detail = response.text[:300]
            raise CatalogError(response.status_code, f'LiteLLM {path} failed: {detail}')
        return response.json()

    # ------------------------------------------------------------------
    # Read side
    # ------------------------------------------------------------------
    def providers(self, configured_counts: Optional[Dict[str, int]] = None,
                  litellm_credentials: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """Provider rows with credential sources and the effective enabled flag.

        A provider has a credential when the deployment provides it (env var on the
        proxy, listed in LLM_PROVIDERS_ENABLED), when an administrator stored one in
        LiteLLM's credential store (`<provider>-default`), or when it uses IAM. An
        administrator can additionally disable a provider at runtime.
        """
        counts = configured_counts or {}
        stored = {}
        for item in litellm_credentials or []:
            info = item.get('credential_info') or {}
            name = item.get('credential_name') or ''
            provider = info.get('custom_llm_provider') or (name[:-8] if name.endswith('-default') else None)
            if provider:
                stored[provider] = {'name': name, 'created_by': info.get('created_by'), 'created_at': info.get('created_at')}
        disabled = set(gateway_settings.disabled_providers())
        rows = []
        for key, spec in PROVIDERS.items():
            credential = dict(spec['credential'])
            sources = []
            if credential['type'] == 'iam':
                sources.append('iam')
            if key in Settings.LLM_PROVIDERS_ENABLED:
                sources.append('env')
            if key in stored:
                sources.append('litellm')
            has_credential = bool(sources)
            enabled = has_credential and key not in disabled
            if credential['type'] == 'api_key':
                how = (
                    f"Add the {spec['display_name']} API key here (stored encrypted in the LiteLLM proxy database), "
                    f"or mount `{credential['env']}` into the proxy via Terraform and list `{key}` in LLM_PROVIDERS_ENABLED."
                )
            else:
                how = 'Grant bedrock:InvokeModel to the proxy task role and add `bedrock` to LLM_PROVIDERS_ENABLED.'
            rows.append({
                'id': key,
                'display_name': spec['display_name'],
                'litellm_prefix': spec['prefix'],
                'enabled': enabled,
                'has_credential': has_credential,
                'credential_sources': sources,
                'stored_credential': stored.get(key),
                'disabled_by_admin': key in disabled,
                'credential': credential,
                'configured_models': counts.get(key, 0),
                'how_to_enable': None if enabled else how,
                'docs': spec['docs'],
            })
        return rows

    def provider_enabled(self, provider: str, litellm_credentials: Optional[List[Dict[str, Any]]] = None) -> bool:
        return any(row['enabled'] for row in self.providers(None, litellm_credentials) if row['id'] == provider)

    async def deployments(self) -> List[Dict[str, Any]]:
        data = await self._get('/model/info')
        rows = []
        for item in data.get('data', []):
            params = item.get('litellm_params', {}) or {}
            info = item.get('model_info', {}) or {}
            litellm_model = params.get('model', '')
            rows.append({
                'model_name': item.get('model_name'),
                'model_id': info.get('id'),
                'provider': provider_for_litellm_model(litellm_model, info.get('litellm_provider')),
                'litellm_model': litellm_model,
                'source': 'db' if info.get('db_model') else 'config',
                'mode': info.get('mode'),
                'input_cost_per_million': _per_million(info.get('input_cost_per_token')),
                'output_cost_per_million': _per_million(info.get('output_cost_per_token')),
                'max_input_tokens': info.get('max_input_tokens'),
                'max_output_tokens': info.get('max_output_tokens'),
                'supports_function_calling': info.get('supports_function_calling'),
                'supports_vision': info.get('supports_vision'),
                'aws_region_name': params.get('aws_region_name'),
                'description': info.get('description'),
            })
        rows.sort(key=lambda r: (r['provider'], r['model_name'] or ''))
        return rows

    async def groups(self) -> List[Dict[str, Any]]:
        try:
            data = await self._get('/model_group/info')
        except Exception:
            return []
        return [
            {
                'model_group': g.get('model_group'),
                'providers': g.get('providers'),
                'mode': g.get('mode'),
                'input_cost_per_million': _per_million(g.get('input_cost_per_token')),
                'output_cost_per_million': _per_million(g.get('output_cost_per_token')),
                'max_input_tokens': g.get('max_input_tokens'),
            }
            for g in data.get('data', [])
        ]

    async def litellm_credentials(self) -> List[Dict[str, Any]]:
        try:
            data = await self._get('/credentials')
        except Exception:
            return []
        return data.get('credentials', []) if isinstance(data, dict) else []

    async def catalog(self) -> Dict[str, Any]:
        deployments = await self.deployments()
        counts: Dict[str, int] = {}
        for row in deployments:
            counts[row['provider']] = counts.get(row['provider'], 0) + 1
        credentials = await self.litellm_credentials()
        disabled_models = set(gateway_settings.disabled_models())
        for row in deployments:
            row['disabled_by_admin'] = row['model_name'] in disabled_models
        return {
            'proxy_url': self._base_url(),
            'env_enabled_providers': Settings.LLM_PROVIDERS_ENABLED,
            'enabled_providers': [p['id'] for p in self.providers(counts, credentials) if p['enabled']],
            'providers': self.providers(counts, credentials),
            'models': deployments,
            'groups': await self.groups(),
            'default_model': gateway_settings.effective_default_model(),
            'judge_model': gateway_settings.effective_judge_model(),
            'allowed_models': gateway_settings.effective_allowed_models(),
            'settings': gateway_settings.effective_view(),
        }

    # Provider lookup for /chat enforcement; cached so a chat request does not
    # pay a proxy round-trip.
    _provider_cache: Dict[str, Any] = {'loaded_at': 0.0, 'map': {}}

    async def provider_of(self, model_name: str) -> Optional[str]:
        import time as _time
        if _time.time() - self._provider_cache['loaded_at'] > 60:
            try:
                self._provider_cache['map'] = {row['model_name']: row['provider'] for row in await self.deployments()}
                self._provider_cache['loaded_at'] = _time.time()
            except Exception:
                pass
        return self._provider_cache['map'].get(model_name)

    async def chat_model_rejection(self, model_name: str) -> Optional[str]:
        """Reason a chat request for this model must be rejected, or None."""
        allowed = gateway_settings.effective_allowed_models()
        if allowed and model_name not in allowed:
            return f'Model {model_name!r} is not in the gateway allowlist: {allowed}'
        if model_name in gateway_settings.disabled_models():
            return f'Model {model_name!r} has been disabled by an administrator'
        provider = await self.provider_of(model_name)
        if provider and provider in gateway_settings.disabled_providers():
            return f'Provider {provider!r} has been disabled by an administrator'
        return None

    async def grouped_models(self, allowed: Optional[List[str]] = None) -> Dict[str, Any]:
        """Chat-screen view: enabled models grouped by enabled providers, honouring the allowlist."""
        deployments = await self.deployments()
        disabled_models = set(gateway_settings.disabled_models())
        disabled_providers = set(gateway_settings.disabled_providers())
        by_provider: Dict[str, List[str]] = {}
        details = []
        for row in deployments:
            name = row['model_name']
            if not name or (allowed and name not in allowed):
                continue
            if row.get('mode') not in (None, 'chat'):
                continue
            if name in disabled_models or row['provider'] in disabled_providers:
                continue
            by_provider.setdefault(row['provider'], [])
            if name not in by_provider[row['provider']]:
                by_provider[row['provider']].append(name)
                details.append({'id': name, 'provider': row['provider'], 'source': row['source'], 'litellm_model': row['litellm_model']})
        return {'by_provider': by_provider, 'details': details}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    async def cost_map(self) -> Dict[str, Any]:
        if self._cost_map is None or (datetime.utcnow() - (self._cost_map_loaded_at or datetime.min)).total_seconds() > 3600:
            response = await self._client_or_create().get(f'{self._base_url()}/public/litellm_model_cost_map')
            response.raise_for_status()
            self._cost_map = response.json()
            self._cost_map_loaded_at = datetime.utcnow()
        return self._cost_map

    @staticmethod
    def _strip_prefix(model_key: str, prefix: str) -> str:
        return model_key[len(prefix) + 1:] if model_key.startswith(prefix + '/') else model_key

    async def available_models(self, provider: str, query: str = '') -> Dict[str, Any]:
        spec = PROVIDERS.get(provider)
        if not spec:
            raise CatalogError(404, f'Unknown provider {provider!r}')
        configured = {row['litellm_model'] for row in await self.deployments()}
        cost_map = await self.cost_map()
        q = (query or '').lower()
        items: Dict[str, Dict[str, Any]] = {}

        for key, info in cost_map.items():
            if not isinstance(info, dict) or info.get('mode') != 'chat':
                continue
            if info.get('litellm_provider') not in spec['cost_map_providers']:
                continue
            model_id = self._strip_prefix(key, spec['prefix'])
            if provider == 'bedrock' and '/' in model_id:
                # price-map keys such as bedrock/us-west-2/... are region-specific duplicates
                continue
            items[model_id] = {
                'id': model_id,
                'litellm_model': f"{spec['prefix']}/{model_id}",
                'input_cost_per_million': _per_million(info.get('input_cost_per_token')),
                'output_cost_per_million': _per_million(info.get('output_cost_per_token')),
                'max_input_tokens': info.get('max_input_tokens'),
                'supports_function_calling': info.get('supports_function_calling'),
                'supports_vision': info.get('supports_vision'),
                'source': 'litellm_cost_map',
            }

        bedrock_note = None
        if spec['discovery'] == 'bedrock':
            live, bedrock_note = self._bedrock_live_models()
            for model in live:
                entry = items.get(model['id'], {
                    'id': model['id'],
                    'litellm_model': f"bedrock/{model['id']}",
                    'input_cost_per_million': None,
                    'output_cost_per_million': None,
                    'max_input_tokens': None,
                    'supports_function_calling': None,
                    'supports_vision': None,
                })
                entry.update({'source': 'bedrock_api', 'available_in_region': True, 'provider_name': model.get('provider_name'),
                              'inference_type': model.get('inference_type')})
                items[model['id']] = entry
            # Bedrock in this region only accepts inference-profile ids (apac./global.) or
            # explicitly on-demand base models; hide price-map entries not confirmed live.
            live_ids = {m['id'] for m in live}
            if live_ids:
                items = {k: v for k, v in items.items() if k in live_ids}

        rows = []
        for model_id, entry in items.items():
            if q and q not in model_id.lower():
                continue
            entry['configured'] = entry['litellm_model'] in configured
            rows.append(entry)
        rows.sort(key=lambda r: (not r.get('available_in_region', False), r['id']))
        return {'provider': provider, 'region': Settings.BEDROCK_REGION if provider == 'bedrock' else None,
                'count': len(rows), 'models': rows, 'note': bedrock_note}

    @staticmethod
    def _bedrock_live_models():
        """Inference profiles and on-demand text models visible to this task's IAM role."""
        try:
            import boto3  # optional at runtime
        except ImportError:
            return [], 'boto3 is not installed; showing LiteLLM price-map entries only'
        try:
            client = boto3.client('bedrock', region_name=Settings.BEDROCK_REGION)
            models = []
            for profile in client.list_inference_profiles(typeEquals='SYSTEM_DEFINED').get('inferenceProfileSummaries', []):
                if profile.get('status') != 'ACTIVE':
                    continue
                models.append({'id': profile['inferenceProfileId'], 'provider_name': profile['inferenceProfileId'].split('.')[1],
                               'inference_type': 'INFERENCE_PROFILE'})
            for fm in client.list_foundation_models(byOutputModality='TEXT').get('modelSummaries', []):
                if 'ON_DEMAND' in fm.get('inferenceTypesSupported', []):
                    models.append({'id': fm['modelId'], 'provider_name': fm.get('providerName'), 'inference_type': 'ON_DEMAND'})
            return models, None
        except Exception as exc:
            return [], f'Bedrock discovery unavailable ({type(exc).__name__}); showing LiteLLM price-map entries only'

    # ------------------------------------------------------------------
    # Write side
    # ------------------------------------------------------------------
    def build_new_model_payload(self, provider: str, model: str, model_name: Optional[str], actor: str,
                                description: str = '', credential_name: Optional[str] = None,
                                litellm_credentials: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        spec = PROVIDERS.get(provider)
        if not spec:
            raise CatalogError(400, f'Unknown provider {provider!r}')
        if not self.provider_enabled(provider, litellm_credentials):
            raise CatalogError(409, f'Provider {provider!r} is not enabled: add a credential and enable it in the Proxy Manager')
        model = (model or '').strip()
        if model.startswith(spec['prefix'] + '/'):
            model = model[len(spec['prefix']) + 1:]
        if not _MODEL_ID_RE.match(model):
            raise CatalogError(400, 'Model id contains unsupported characters')
        alias = (model_name or '').strip() or model
        if not _ALIAS_RE.match(alias):
            raise CatalogError(400, 'Model name contains unsupported characters')
        params: Dict[str, Any] = {'model': f"{spec['prefix']}/{model}"}
        if spec['credential']['type'] == 'api_key':
            # Prefer a credential stored in LiteLLM by an administrator; otherwise
            # reference the proxy's environment. Never a key supplied by the UI.
            if credential_name:
                params['litellm_credential_name'] = credential_name
            else:
                params['api_key'] = f"os.environ/{spec['credential']['env']}"
        if provider == 'bedrock':
            params['aws_region_name'] = Settings.BEDROCK_REGION
        return {
            'model_name': alias,
            'litellm_params': params,
            'model_info': {
                'description': description or f'Added via admin catalogue by {actor}',
                'added_by': actor,
                'added_at': datetime.utcnow().isoformat() + 'Z',
            },
        }

    async def add_model(self, provider: str, model: str, model_name: Optional[str], actor: str,
                        description: str = '') -> Dict[str, Any]:
        credentials = await self.litellm_credentials()
        stored = next((c.get('credential_name') for c in credentials
                       if (c.get('credential_info') or {}).get('custom_llm_provider') == provider
                       or c.get('credential_name') == f'{provider}-default'), None)
        payload = self.build_new_model_payload(provider, model, model_name, actor, description,
                                               credential_name=stored, litellm_credentials=credentials)
        existing = {row['model_name'] for row in await self.deployments()}
        if payload['model_name'] in existing:
            raise CatalogError(409, f"A model named {payload['model_name']!r} already exists")
        result = await self._post('/model/new', payload)
        record_catalog_event('model_added', actor, {'provider': provider, 'model_name': payload['model_name'],
                                                    'litellm_model': payload['litellm_params']['model']})
        return {'model_name': payload['model_name'], 'litellm_model': payload['litellm_params']['model'],
                'provider': provider, 'litellm_response': result}

    async def delete_model(self, model_id: str, actor: str) -> Dict[str, Any]:
        rows = [row for row in await self.deployments() if row['model_id'] == model_id]
        if not rows:
            raise CatalogError(404, 'Model not found')
        row = rows[0]
        if row['source'] != 'db':
            raise CatalogError(409, f"{row['model_name']} is defined in litellm/config.yaml; remove it there and redeploy the proxy")
        result = await self._post('/model/delete', {'id': model_id})
        record_catalog_event('model_removed', actor, {'provider': row['provider'], 'model_name': row['model_name'],
                                                      'litellm_model': row['litellm_model']})
        return {'deleted': row['model_name'], 'litellm_response': result}


class CatalogError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


model_catalog = ModelCatalog()
