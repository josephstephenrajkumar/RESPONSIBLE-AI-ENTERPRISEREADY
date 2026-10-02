"""Unit tests for the admin model catalogue (LiteLLM-backed).

Run from backend/:  ./venv/bin/python -m unittest discover -s tests -v
"""

import asyncio
import json
import os
import unittest

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ['LLM_GATEWAY_MODE'] = 'proxy'
os.environ['LITELLM_PROXY_URL'] = 'http://litellm.test'
os.environ['LITELLM_API_KEY'] = 'sk-test-virtual-key'
os.environ['LLM_PROVIDERS_ENABLED'] = 'groq,bedrock'

import httpx  # noqa: E402

from app import database  # noqa: E402
from app.config import Settings  # noqa: E402
from app.model_catalog import CatalogError, ModelCatalog, provider_for_litellm_model  # noqa: E402

MODEL_INFO = {'data': [
    {'model_name': 'openai/gpt-oss-120b', 'litellm_params': {'model': 'groq/openai/gpt-oss-120b'},
     'model_info': {'id': 'id-groq', 'db_model': False, 'litellm_provider': 'groq', 'mode': 'chat',
                    'input_cost_per_token': 1.5e-07, 'output_cost_per_token': 6e-07, 'max_input_tokens': 131072}},
    {'model_name': 'nova-micro', 'litellm_params': {'model': 'bedrock/apac.amazon.nova-micro-v1:0', 'aws_region_name': 'ap-southeast-1'},
     'model_info': {'id': 'id-nova', 'db_model': True, 'litellm_provider': 'bedrock_converse', 'mode': 'chat',
                    'input_cost_per_token': 3.5e-08, 'output_cost_per_token': 1.4e-07}},
]}
COST_MAP = {
    'groq/openai/gpt-oss-20b': {'litellm_provider': 'groq', 'mode': 'chat', 'input_cost_per_token': 7.5e-08, 'output_cost_per_token': 3e-07, 'max_input_tokens': 131072},
    'groq/whisper-large-v3': {'litellm_provider': 'groq', 'mode': 'audio_transcription'},
    'anthropic/claude-3-5-haiku-20241022': {'litellm_provider': 'anthropic', 'mode': 'chat'},
    'apac.amazon.nova-micro-v1:0': {'litellm_provider': 'bedrock_converse', 'mode': 'chat', 'input_cost_per_token': 3.5e-08, 'output_cost_per_token': 1.4e-07},
    'bedrock/us-west-2/anthropic.claude-3-haiku-20240307-v1:0': {'litellm_provider': 'bedrock', 'mode': 'chat'},
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == '/model/info':
        assert request.headers['authorization'] == 'Bearer sk-test-virtual-key'
        return httpx.Response(200, json=MODEL_INFO)
    if path == '/model_group/info':
        return httpx.Response(200, json={'data': [{'model_group': 'judge-fast', 'providers': ['groq'], 'mode': 'chat'}]})
    if path == '/public/litellm_model_cost_map':
        return httpx.Response(200, json=COST_MAP)
    if path == '/model/new':
        body = json.loads(request.content)
        _handler.last_new = body
        return httpx.Response(200, json={'model_id': 'new-id', 'model_name': body['model_name']})
    if path == '/model/delete':
        _handler.last_delete = json.loads(request.content)
        return httpx.Response(200, json={'deleted_model': 'nova-micro'})
    return httpx.Response(404, json={'error': 'not found'})


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        # Settings is evaluated once per process; pin what these tests assume
        # regardless of which test module imported the app first.
        self._saved = (Settings.LLM_PROVIDERS_ENABLED, Settings.LITELLM_PROXY_URL, Settings.LITELLM_API_KEY, Settings.LITELLM_ADMIN_API_KEY)
        Settings.LLM_PROVIDERS_ENABLED = ['groq', 'bedrock']
        Settings.LITELLM_PROXY_URL = 'http://litellm.test'
        Settings.LITELLM_API_KEY = 'sk-test-virtual-key'
        Settings.LITELLM_ADMIN_API_KEY = ''
        self.catalog = ModelCatalog()
        self.catalog._client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
        # Bedrock live discovery is not available in unit tests.
        self.catalog._bedrock_live_models = staticmethod(lambda: ([], 'no aws'))

    def tearDown(self):
        (Settings.LLM_PROVIDERS_ENABLED, Settings.LITELLM_PROXY_URL, Settings.LITELLM_API_KEY, Settings.LITELLM_ADMIN_API_KEY) = self._saved

    def test_provider_mapping(self):
        self.assertEqual(provider_for_litellm_model('groq/openai/gpt-oss-120b', 'groq'), 'groq')
        self.assertEqual(provider_for_litellm_model('bedrock/apac.amazon.nova-micro-v1:0', 'bedrock_converse'), 'bedrock')
        self.assertEqual(provider_for_litellm_model('anthropic/claude-3-5-haiku', None), 'anthropic')

    def test_catalog_lists_deployments_and_provider_status(self):
        result = asyncio.run(self.catalog.catalog())
        models = {m['model_name']: m for m in result['models']}
        self.assertEqual(models['openai/gpt-oss-120b']['source'], 'config')
        self.assertEqual(models['nova-micro']['source'], 'db')
        self.assertEqual(models['nova-micro']['provider'], 'bedrock')
        self.assertAlmostEqual(models['openai/gpt-oss-120b']['input_cost_per_million'], 0.15)
        providers = {p['id']: p for p in result['providers']}
        self.assertTrue(providers['groq']['enabled'] and providers['bedrock']['enabled'])
        self.assertFalse(providers['anthropic']['enabled'])
        self.assertIn('ANTHROPIC_API_KEY', providers['anthropic']['how_to_enable'])
        self.assertEqual(providers['groq']['configured_models'], 1)

    def test_grouped_models_for_chat_screen(self):
        grouped = asyncio.run(self.catalog.grouped_models(None))
        self.assertEqual(grouped['by_provider'], {'bedrock': ['nova-micro'], 'groq': ['openai/gpt-oss-120b']})
        grouped = asyncio.run(self.catalog.grouped_models(['nova-micro']))
        self.assertEqual(list(grouped['by_provider'].keys()), ['bedrock'])

    def test_available_models_filters_chat_and_provider(self):
        groq = asyncio.run(self.catalog.available_models('groq'))
        ids = [m['id'] for m in groq['models']]
        self.assertEqual(ids, ['openai/gpt-oss-20b'])          # audio model excluded; prefix stripped
        self.assertEqual(groq['models'][0]['litellm_model'], 'groq/openai/gpt-oss-20b')
        bedrock = asyncio.run(self.catalog.available_models('bedrock'))
        ids = [m['id'] for m in bedrock['models']]
        self.assertEqual(ids, ['apac.amazon.nova-micro-v1:0'])  # region-specific duplicate excluded
        self.assertTrue(bedrock['models'][0]['configured'])
        with self.assertRaises(CatalogError):
            asyncio.run(self.catalog.available_models('nope'))

    def test_add_model_references_env_not_raw_key(self):
        result = asyncio.run(self.catalog.add_model('groq', 'groq/openai/gpt-oss-20b', None, 'tester'))
        body = _handler.last_new
        self.assertEqual(body['model_name'], 'openai/gpt-oss-20b')
        self.assertEqual(body['litellm_params']['model'], 'groq/openai/gpt-oss-20b')
        self.assertEqual(body['litellm_params']['api_key'], 'os.environ/GROQ_API_KEY')
        self.assertEqual(result['provider'], 'groq')

    def test_add_bedrock_model_sets_region_and_no_key(self):
        asyncio.run(self.catalog.add_model('bedrock', 'apac.anthropic.claude-3-haiku-20240307-v1:0', 'claude-haiku', 'tester'))
        body = _handler.last_new
        self.assertEqual(body['model_name'], 'claude-haiku')
        self.assertEqual(body['litellm_params']['aws_region_name'], Settings.BEDROCK_REGION)
        self.assertNotIn('api_key', body['litellm_params'])

    def test_add_rejects_disabled_provider_duplicates_and_bad_ids(self):
        with self.assertRaises(CatalogError) as ctx:
            asyncio.run(self.catalog.add_model('anthropic', 'claude-3-5-haiku-20241022', None, 'tester'))
        self.assertEqual(ctx.exception.status_code, 409)
        with self.assertRaises(CatalogError) as ctx:
            asyncio.run(self.catalog.add_model('groq', 'openai/gpt-oss-120b', None, 'tester'))   # already exists
        self.assertEqual(ctx.exception.status_code, 409)
        with self.assertRaises(CatalogError):
            asyncio.run(self.catalog.add_model('groq', 'bad model;rm -rf', None, 'tester'))

    def test_delete_only_runtime_models(self):
        with self.assertRaises(CatalogError) as ctx:
            asyncio.run(self.catalog.delete_model('id-groq', 'tester'))      # config.yaml model
        self.assertEqual(ctx.exception.status_code, 409)
        result = asyncio.run(self.catalog.delete_model('id-nova', 'tester'))
        self.assertEqual(_handler.last_delete, {'id': 'id-nova'})
        self.assertEqual(result['deleted'], 'nova-micro')
        with database.SessionLocal() as session:
            actions = [row.action for row in session.query(database.PolicyAuditEvent).all()]
        self.assertIn('model_removed', actions)


if __name__ == '__main__':
    unittest.main()
