"""Single egress point for every LLM call made by the AI Gateway.

Architecture (see docs/ARCHITECTURE_DESIGN.md, section 4):

    Chat client -> AI Gateway (this service: policy enforcement)
                      -> LiteLLM proxy (model gateway: keys, routing, retries,
                         fallbacks, budgets, cost metering)
                          -> Groq / OpenAI / Bedrock / ...

Nothing else in the backend is allowed to open a connection to a model
provider. Chat answers *and* the Ragas / TruLens judge calls all go through
`llm_client`, so one place records tokens, cost, latency and errors for the
FinOps and AIOps dashboards, and the application tier never holds a provider
API key when LLM_GATEWAY_MODE=proxy.
"""

import contextvars
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings
from app.database import append_llm_usage_event
from app.framework_mode.langfuse_observability import (
    is_langfuse_configured,
    langfuse_observe,
    update_current_llm_trace,
)
from app.pricing import estimate_cost

SYSTEM_PROMPT = '''You are a responsible AI assistant.
Follow these rules:
- Be accurate and honest.
- Say when you are uncertain.
- Do not expose private data.
- Avoid harmful, biased, or discriminatory content.
- Explain reasoning at a high level when requested.
'''

# Attribution for usage metering. /chat binds the caller's identity once per
# request; judge calls made deeper in the pipeline (ragas, trulens) inherit it
# through the context variable instead of threading six parameters through
# every framework adapter.
_request_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    'llm_request_context', default={}
)

# LiteLLM response headers we read. Everything is optional: a proxy version
# that omits a header simply yields None for that field.
_HEADER_COST = 'x-litellm-response-cost'
_HEADER_CALL_ID = 'x-litellm-call-id'
_HEADER_MODEL_ID = 'x-litellm-model-id'
_HEADER_API_BASE = 'x-litellm-model-api-base'
_HEADER_RETRIES = 'x-litellm-attempted-retries'
_HEADER_FALLBACKS = 'x-litellm-attempted-fallbacks'
_HEADER_OVERHEAD_MS = 'x-litellm-overhead-duration-ms'
_HEADER_KEY_SPEND = 'x-litellm-key-spend'


def bind_request_context(**fields: Any) -> contextvars.Token:
    return _request_context.set({key: value for key, value in fields.items() if value is not None})


def reset_request_context(token: contextvars.Token) -> None:
    _request_context.reset(token)


def current_request_context() -> Dict[str, Any]:
    return dict(_request_context.get())


def _to_float(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _to_int(value: Optional[str]) -> Optional[int]:
    number = _to_float(value)
    return int(number) if number is not None else None


class LLMGatewayClient:
    def __init__(self):
        mode = Settings.LLM_GATEWAY_MODE
        self.mode = mode if mode in ('proxy', 'direct') else 'proxy'
        self.default_model = Settings.LLM_DEFAULT_MODEL
        self.judge_model = Settings.LLM_JUDGE_MODEL
        self._async_client: Optional[httpx.AsyncClient] = None
        self._sync_client: Optional[httpx.Client] = None

    # ------------------------------------------------------------------
    # Connection details
    # ------------------------------------------------------------------
    @property
    def base_url(self) -> str:
        if self.mode == 'proxy':
            return Settings.LITELLM_PROXY_URL
        return Settings.GROQ_API_URL.rstrip('/')

    @property
    def provider_label(self) -> str:
        return 'litellm' if self.mode == 'proxy' else 'groq'

    def _api_key(self) -> str:
        return Settings.LITELLM_API_KEY if self.mode == 'proxy' else Settings.GROQ_API_KEY

    def _headers(self) -> Dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        api_key = self._api_key()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        return headers

    def _limits(self) -> httpx.Limits:
        return httpx.Limits(
            max_connections=Settings.LLM_MAX_CONNECTIONS,
            max_keepalive_connections=Settings.LLM_MAX_KEEPALIVE_CONNECTIONS,
        )

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=Settings.LLM_TIMEOUT_SECONDS, limits=self._limits())
        return self._async_client

    def _get_sync_client(self) -> httpx.Client:
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=Settings.LLM_TIMEOUT_SECONDS, limits=self._limits())
        return self._sync_client

    async def close(self) -> None:
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None

    # ------------------------------------------------------------------
    # Request / response shaping
    # ------------------------------------------------------------------
    def resolve_model(self, model: Optional[str], purpose: str = 'chat') -> str:
        if model:
            return model
        return self.judge_model if purpose.startswith('judge') else self.default_model

    def model_allowed(self, model: str) -> bool:
        return not Settings.LLM_ALLOWED_MODELS or model in Settings.LLM_ALLOWED_MODELS

    def _build_payload(self, messages: List[Dict[str, str]], model: str, temperature: float,
                       max_tokens: int, purpose: str, context: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            'model': model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        if self.mode != 'proxy':
            return payload

        # `user` is the OpenAI end-user field; LiteLLM records it as the spend
        # log end_user. `metadata.tags` become LiteLLM request tags so spend can
        # be sliced by tenant / client / agent / purpose on the proxy side too.
        user_id = context.get('user_id')
        if user_id:
            payload['user'] = str(user_id)
        tags = [f'purpose:{purpose}', f'mode:{context.get("mode", "unknown")}']
        for key in ('tenant_id', 'client_id', 'agent_id', 'session_id'):
            value = context.get(key)
            if value:
                tags.append(f'{key}:{value}')
        payload['metadata'] = {
            'tags': tags,
            'generation_name': f'rai-gateway.{purpose}',
            'request_id': context.get('request_id', ''),
            'tenant_id': context.get('tenant_id', ''),
        }
        return payload

    def _normalize_success(self, data: Dict[str, Any], headers: httpx.Headers, requested_model: str,
                           latency_ms: int) -> Dict[str, Any]:
        choices = data.get('choices') or [{}]
        answer = (choices[0].get('message') or {}).get('content', '') if choices else ''
        finish_reason = (choices[0].get('finish_reason') or '') if choices else ''
        usage = data.get('usage') or {}
        prompt_tokens = int(usage.get('prompt_tokens') or 0)
        completion_tokens = int(usage.get('completion_tokens') or 0)
        total_tokens = int(usage.get('total_tokens') or (prompt_tokens + completion_tokens))
        served_model = data.get('model') or requested_model

        cost = _to_float(headers.get(_HEADER_COST)) if self.mode == 'proxy' else None
        cost_source = 'litellm' if cost is not None else None
        if cost is None:
            cost = estimate_cost(served_model or requested_model, prompt_tokens, completion_tokens)
            cost_source = 'estimated' if cost is not None else 'unknown'

        return {
            'answer': answer,
            'provider': self.provider_label,
            'model': requested_model,
            'served_model': served_model,
            'request_id': str(uuid.uuid4()),
            'call_id': headers.get(_HEADER_CALL_ID) or data.get('id', ''),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'tokens': total_tokens,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'cost_usd': cost,
            'cost_source': cost_source,
            'latency_ms': latency_ms,
            'proxy_overhead_ms': _to_int(headers.get(_HEADER_OVERHEAD_MS)),
            'retries': _to_int(headers.get(_HEADER_RETRIES)) or 0,
            'fallbacks': _to_int(headers.get(_HEADER_FALLBACKS)) or 0,
            'api_base': headers.get(_HEADER_API_BASE, ''),
            'key_spend': _to_float(headers.get(_HEADER_KEY_SPEND)),
            'status': 'success',
            'finish_reason': finish_reason,
            'metadata': data,
        }

    def _normalize_error(self, exc: Exception, requested_model: str, latency_ms: int) -> Dict[str, Any]:
        http_status = None
        detail = str(exc)
        if isinstance(exc, httpx.HTTPStatusError):
            http_status = exc.response.status_code
            try:
                body = exc.response.json()
                detail = body.get('error', {}).get('message') if isinstance(body.get('error'), dict) else body.get('detail') or detail
            except Exception:
                detail = exc.response.text[:300] or detail
        error_type = type(exc).__name__ if http_status is None else f'HTTP_{http_status}'
        if isinstance(exc, httpx.TimeoutException):
            error_type = 'Timeout'
        elif isinstance(exc, httpx.ConnectError):
            error_type = 'ConnectError'
        return {
            'answer': f'LLM gateway request failed ({error_type}): {detail}',
            'provider': f'{self.provider_label}-error',
            'model': requested_model,
            'served_model': '',
            'request_id': str(uuid.uuid4()),
            'call_id': '',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'tokens': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'cost_usd': 0.0,
            'cost_source': 'none',
            'latency_ms': latency_ms,
            'proxy_overhead_ms': None,
            'retries': 0,
            'fallbacks': 0,
            'api_base': '',
            'status': 'error',
            'error_type': error_type,
            'http_status': http_status,
            'metadata': {'error': detail},
        }

    def _unconfigured_response(self, requested_model: str) -> Dict[str, Any]:
        reason = (
            'GROQ_API_KEY is not configured for LLM_GATEWAY_MODE=direct'
            if self.mode == 'direct'
            else 'LiteLLM proxy is not configured'
        )
        return {
            'answer': f'Unable to reach the LLM gateway: {reason}.',
            'provider': f'{self.provider_label}-fallback',
            'model': requested_model,
            'served_model': '',
            'request_id': str(uuid.uuid4()),
            'call_id': '',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'tokens': 0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'cost_usd': 0.0,
            'cost_source': 'none',
            'latency_ms': 0,
            'proxy_overhead_ms': None,
            'retries': 0,
            'fallbacks': 0,
            'api_base': '',
            'status': 'unconfigured',
            'error_type': 'Unconfigured',
            'metadata': {'notes': reason},
        }

    def _record_usage(self, result: Dict[str, Any], purpose: str, context: Dict[str, Any]) -> None:
        # Metering must never break a chat response: swallow persistence errors.
        try:
            append_llm_usage_event({
                'request_id': context.get('request_id') or result.get('request_id', ''),
                'call_id': result.get('call_id', ''),
                'timestamp': result.get('timestamp'),
                'user_id': context.get('user_id', 'anonymous'),
                'user_email': context.get('user_email', ''),
                'tenant_id': context.get('tenant_id', 'default'),
                'client_id': context.get('client_id', ''),
                'agent_id': context.get('agent_id', ''),
                'session_id': context.get('session_id', ''),
                'mode': context.get('mode', 'unknown'),
                'purpose': purpose,
                'requested_model': result.get('model', ''),
                'served_model': result.get('served_model', ''),
                'provider': result.get('provider', ''),
                'gateway_mode': self.mode,
                'api_base': result.get('api_base', ''),
                'prompt_tokens': result.get('prompt_tokens', 0),
                'completion_tokens': result.get('completion_tokens', 0),
                'total_tokens': result.get('tokens', 0),
                'cost_usd': result.get('cost_usd') or 0.0,
                'cost_source': result.get('cost_source', 'unknown'),
                'latency_ms': result.get('latency_ms', 0),
                'proxy_overhead_ms': result.get('proxy_overhead_ms'),
                'retries': result.get('retries', 0),
                'fallbacks': result.get('fallbacks', 0),
                'status': result.get('status', 'unknown'),
                'error_type': result.get('error_type', ''),
                'http_status': result.get('http_status'),
            })
        except Exception:
            pass

    def _ready(self) -> bool:
        if self.mode == 'direct':
            return bool(Settings.GROQ_API_KEY)
        return bool(Settings.LITELLM_PROXY_URL)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def complete(self, messages: List[Dict[str, str]], *, model: Optional[str] = None,
                       temperature: float = 0.2, max_tokens: int = 800, purpose: str = 'chat',
                       observe: bool = False) -> Dict[str, Any]:
        if observe and is_langfuse_configured():
            return await self._complete_observed(
                messages, model=model, temperature=temperature, max_tokens=max_tokens, purpose=purpose
            )
        return await self._complete(messages, model=model, temperature=temperature, max_tokens=max_tokens, purpose=purpose)

    @langfuse_observe(name='llm_completion', as_type='generation')
    async def _complete_observed(self, messages, *, model, temperature, max_tokens, purpose):
        result = await self._complete(messages, model=model, temperature=temperature, max_tokens=max_tokens, purpose=purpose)
        update_current_llm_trace(
            result.get('request_id', ''),
            {
                'message': messages[-1].get('content', '') if messages else '',
                'model': result.get('model'),
                'temperature': temperature,
                'max_tokens': max_tokens,
                'mode': current_request_context().get('mode', 'framework'),
                'purpose': purpose,
            },
            {
                'answer': result.get('answer', ''),
                'provider': result.get('provider', ''),
                'model': result.get('served_model') or result.get('model', ''),
                'timestamp': result.get('timestamp', ''),
                'metadata': result.get('metadata', {}),
            },
        )
        return result

    async def _complete(self, messages, *, model, temperature, max_tokens, purpose) -> Dict[str, Any]:
        context = current_request_context()
        requested_model = self.resolve_model(model, purpose)
        if not self._ready():
            result = self._unconfigured_response(requested_model)
            self._record_usage(result, purpose, context)
            return result

        payload = self._build_payload(messages, requested_model, temperature, max_tokens, purpose, context)
        client = self._get_async_client()
        started = time.perf_counter()
        try:
            response = await client.post(f'{self.base_url}/chat/completions', headers=self._headers(), json=payload)
            latency_ms = int((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            result = self._normalize_success(response.json(), response.headers, requested_model, latency_ms)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            result = self._normalize_error(exc, requested_model, latency_ms)
        self._record_usage(result, purpose, context)
        return result

    def complete_sync(self, messages: List[Dict[str, str]], *, model: Optional[str] = None,
                      temperature: float = 0.0, max_tokens: int = 200, purpose: str = 'judge') -> Dict[str, Any]:
        """Blocking variant for adapters that only expose a sync hook (TruLens)."""
        context = current_request_context()
        requested_model = self.resolve_model(model, purpose)
        if not self._ready():
            result = self._unconfigured_response(requested_model)
            self._record_usage(result, purpose, context)
            return result

        payload = self._build_payload(messages, requested_model, temperature, max_tokens, purpose, context)
        client = self._get_sync_client()
        started = time.perf_counter()
        try:
            response = client.post(f'{self.base_url}/chat/completions', headers=self._headers(), json=payload)
            latency_ms = int((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            result = self._normalize_success(response.json(), response.headers, requested_model, latency_ms)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            result = self._normalize_error(exc, requested_model, latency_ms)
        self._record_usage(result, purpose, context)
        return result

    async def chat(self, message: str, *, model: Optional[str] = None, temperature: float = 0.2,
                   max_tokens: int = 800, observe: bool = False) -> Dict[str, Any]:
        """Convenience wrapper used by /chat: system prompt + single user turn."""
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': message},
        ]
        return await self.complete(
            messages, model=model, temperature=temperature, max_tokens=max_tokens, purpose='chat', observe=observe
        )

    async def list_models(self) -> List[str]:
        if self.mode == 'direct':
            return [self.default_model]
        client = self._get_async_client()
        response = await client.get(f'{self.base_url}/models', headers=self._headers(), timeout=5.0)
        response.raise_for_status()
        data = response.json().get('data', [])
        return sorted({item.get('id') for item in data if item.get('id')})

    async def health(self) -> Dict[str, Any]:
        """Live dependency check used by /gateway/health and the AIOps dashboard."""
        info: Dict[str, Any] = {
            'mode': self.mode,
            'provider': self.provider_label,
            'base_url': self.base_url,
            'default_model': self.default_model,
            'judge_model': self.judge_model,
            'allowed_models': Settings.LLM_ALLOWED_MODELS,
            'credential_configured': bool(self._api_key()),
            'application_holds_provider_key': bool(Settings.GROQ_API_KEY) if self.mode == 'proxy' else True,
        }
        started = time.perf_counter()
        try:
            models = await self.list_models()
            info.update({
                'status': 'ok',
                'reachable': True,
                'latency_ms': int((time.perf_counter() - started) * 1000),
                'models': models,
                'model_count': len(models),
                'default_model_available': self.default_model in models if models else None,
            })
        except Exception as exc:
            info.update({
                'status': 'unreachable',
                'reachable': False,
                'latency_ms': int((time.perf_counter() - started) * 1000),
                'models': [],
                'model_count': 0,
                'error': f'{type(exc).__name__}: {exc}',
            })
        return info


llm_client = LLMGatewayClient()
