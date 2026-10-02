"""Unit tests for the LiteLLM gateway client.

Run from backend/:
    ./venv/bin/python -m unittest discover -s tests -v

These use an in-memory SQLite database and an httpx MockTransport standing in
for the LiteLLM proxy, so they verify the gateway-side contract (headers read,
cost attribution, error normalisation, metering rows) without a live proxy.
"""

import asyncio
import json
import os
import unittest

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ['LLM_GATEWAY_MODE'] = 'proxy'
os.environ['LITELLM_PROXY_URL'] = 'http://litellm.test'
os.environ['LITELLM_API_KEY'] = 'sk-test-virtual-key'
os.environ['GROQ_API_KEY'] = ''  # the application tier must not need a provider key

import httpx  # noqa: E402

from app import database  # noqa: E402
from app.llm_client import (  # noqa: E402
    LLMGatewayClient,
    bind_request_context,
    reset_request_context,
)
from app.pricing import estimate_cost  # noqa: E402


def _proxy_response(request: httpx.Request, *, cost_header=True, status_code=200, model='groq/llama-3.3-70b-versatile'):
    body = json.loads(request.content)
    assert request.headers['authorization'] == 'Bearer sk-test-virtual-key'
    assert body['metadata']['tags'], 'spend tags must be forwarded to the proxy'
    headers = {
        'x-litellm-call-id': 'call-123',
        'x-litellm-model-id': 'model-abc',
        'x-litellm-attempted-retries': '1',
        'x-litellm-attempted-fallbacks': '0',
        'x-litellm-overhead-duration-ms': '12',
        'x-litellm-model-api-base': 'https://api.groq.com/openai/v1',
    }
    if cost_header:
        headers['x-litellm-response-cost'] = '0.000123'
    payload = {
        'id': 'chatcmpl-1',
        'model': model,
        'choices': [{'message': {'role': 'assistant', 'content': 'hello from the proxy'}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150},
    }
    return httpx.Response(status_code, json=payload, headers=headers)


class LLMGatewayClientTests(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        with database.SessionLocal() as session:
            session.query(database.LLMUsageEventRecord).delete()
            session.commit()
        self.client = LLMGatewayClient()

    def _install_transport(self, handler):
        self.client._async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.client._sync_client = httpx.Client(transport=httpx.MockTransport(handler))

    def _usage_rows(self):
        with database.SessionLocal() as session:
            return session.query(database.LLMUsageEventRecord).order_by(database.LLMUsageEventRecord.id).all()

    def test_proxy_mode_needs_no_provider_key(self):
        self.assertEqual(self.client.mode, 'proxy')
        self.assertTrue(self.client._ready())
        self.assertEqual(self.client.base_url, 'http://litellm.test')
        self.assertEqual(self.client.provider_label, 'litellm')

    def test_success_reads_litellm_headers_and_meters_usage(self):
        self._install_transport(lambda request: _proxy_response(request))
        token = bind_request_context(
            request_id='req-1', user_id='u1', tenant_id='acme', client_id='web', agent_id='a1', mode='framework'
        )
        try:
            result = asyncio.run(self.client.chat('hi', model='llama-3.3-70b-versatile'))
        finally:
            reset_request_context(token)

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['answer'], 'hello from the proxy')
        self.assertEqual(result['provider'], 'litellm')
        self.assertEqual(result['served_model'], 'groq/llama-3.3-70b-versatile')
        self.assertAlmostEqual(result['cost_usd'], 0.000123)
        self.assertEqual(result['cost_source'], 'litellm')
        self.assertEqual(result['tokens'], 150)
        self.assertEqual(result['retries'], 1)
        self.assertEqual(result['proxy_overhead_ms'], 12)
        self.assertEqual(result['call_id'], 'call-123')

        rows = self._usage_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.request_id, 'req-1')
        self.assertEqual(row.tenant_id, 'acme')
        self.assertEqual(row.purpose, 'chat')
        self.assertEqual(row.total_tokens, 150)
        self.assertAlmostEqual(row.cost_usd, 0.000123)
        self.assertEqual(row.status, 'success')

    def test_missing_cost_header_falls_back_to_estimate(self):
        self._install_transport(lambda request: _proxy_response(request, cost_header=False))
        result = asyncio.run(self.client.complete([{'role': 'user', 'content': 'x'}], model='llama-3.3-70b-versatile'))
        self.assertEqual(result['cost_source'], 'estimated')
        self.assertAlmostEqual(result['cost_usd'], estimate_cost('llama-3.3-70b-versatile', 100, 50))

    def test_unknown_model_without_cost_header_is_unknown_cost(self):
        self._install_transport(lambda request: _proxy_response(request, cost_header=False, model='some/unknown-model'))
        result = asyncio.run(self.client.complete([{'role': 'user', 'content': 'x'}], model='unknown-model'))
        self.assertEqual(result['cost_source'], 'unknown')
        self.assertIsNone(result['cost_usd'])

    def test_http_error_is_normalised_and_metered(self):
        def handler(request):
            return httpx.Response(429, json={'error': {'message': 'rate limited'}})

        self._install_transport(handler)
        result = asyncio.run(self.client.complete([{'role': 'user', 'content': 'x'}], purpose='judge_fairness'))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['provider'], 'litellm-error')
        self.assertEqual(result['error_type'], 'HTTP_429')
        self.assertEqual(result['http_status'], 429)
        self.assertIn('rate limited', result['answer'])

        rows = self._usage_rows()
        self.assertEqual(rows[0].status, 'error')
        self.assertEqual(rows[0].http_status, 429)
        self.assertEqual(rows[0].purpose, 'judge_fairness')
        # Judge calls default to the judge model, not the chat model.
        self.assertEqual(rows[0].requested_model, self.client.judge_model)

    def test_connect_error_does_not_fall_back_to_direct_provider(self):
        def handler(request):
            raise httpx.ConnectError('connection refused', request=request)

        self._install_transport(handler)
        result = asyncio.run(self.client.chat('hi'))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['error_type'], 'ConnectError')
        # No silent bypass of the proxy: the provider label stays litellm-*.
        self.assertTrue(result['provider'].startswith('litellm'))

    def test_sync_path_used_by_trulens(self):
        self._install_transport(lambda request: _proxy_response(request))
        result = self.client.complete_sync([{'role': 'user', 'content': 'grade this'}], purpose='judge_explainability')
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self._usage_rows()[0].purpose, 'judge_explainability')

    def test_model_allowlist(self):
        from app.config import Settings

        original = Settings.LLM_ALLOWED_MODELS
        try:
            Settings.LLM_ALLOWED_MODELS = ['llama-3.3-70b-versatile']
            self.assertTrue(self.client.model_allowed('llama-3.3-70b-versatile'))
            self.assertFalse(self.client.model_allowed('gpt-4o'))
            Settings.LLM_ALLOWED_MODELS = []
            self.assertTrue(self.client.model_allowed('gpt-4o'))
        finally:
            Settings.LLM_ALLOWED_MODELS = original


class FinOpsAggregationTests(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        with database.SessionLocal() as session:
            session.query(database.LLMUsageEventRecord).delete()
            session.commit()

    def _event(self, **overrides):
        base = {
            'request_id': 'r', 'purpose': 'chat', 'requested_model': 'm', 'served_model': 'm',
            'provider': 'litellm', 'tenant_id': 'acme', 'user_id': 'u', 'prompt_tokens': 10,
            'completion_tokens': 5, 'total_tokens': 15, 'cost_usd': 0.001, 'cost_source': 'litellm',
            'latency_ms': 100, 'status': 'success',
        }
        base.update(overrides)
        return base

    def test_finops_summary_totals_and_budget(self):
        database.append_llm_usage_event(self._event())
        database.append_llm_usage_event(self._event(purpose='judge_fairness', cost_usd=0.0005, latency_ms=50))
        database.append_llm_usage_event(self._event(status='error', cost_usd=0.0, total_tokens=0, error_type='Timeout'))

        summary = database.get_finops_summary(days=7, monthly_budget_usd=1.0)
        self.assertEqual(summary['totals']['requests'], 3)
        self.assertEqual(summary['totals']['errors'], 1)
        self.assertAlmostEqual(summary['totals']['cost_usd'], 0.0015)
        self.assertAlmostEqual(summary['unit_economics']['judge_share_of_cost'], 0.0005 / 0.0015, places=3)
        self.assertEqual(summary['budget']['status'], 'ok')
        self.assertEqual(summary['by_tenant'][0]['key'], 'acme')
        self.assertEqual({row['key'] for row in summary['by_purpose']}, {'chat', 'judge_fairness'})

    def test_aiops_summary_latency_and_errors(self):
        for latency in (100, 200, 300, 400, 1000):
            database.append_llm_usage_event(self._event(latency_ms=latency))
        database.append_llm_usage_event(self._event(status='error', error_type='Timeout', http_status=None))
        database.append_llm_usage_event(self._event(status='error', error_type='HTTP_429', http_status=429))

        summary = database.get_aiops_summary(hours=24)
        self.assertEqual(summary['totals']['requests'], 7)
        self.assertEqual(summary['totals']['errors'], 2)
        self.assertEqual(summary['totals']['timeouts'], 1)
        self.assertEqual(summary['totals']['rate_limited'], 1)
        self.assertEqual(summary['latency']['p50_ms'], 300)
        self.assertEqual(summary['latency']['p99_ms'], 1000)
        self.assertEqual(summary['by_error_type'], {'Timeout': 1, 'HTTP_429': 1})
        self.assertEqual(len(summary['recent_errors']), 2)


if __name__ == '__main__':
    unittest.main()
