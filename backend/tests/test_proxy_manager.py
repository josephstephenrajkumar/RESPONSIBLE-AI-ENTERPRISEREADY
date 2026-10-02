"""Unit tests for the Proxy Manager layer: runtime settings, governed LiteLLM access,
provider enablement and chat enforcement.  Run from backend/:
    ./venv/bin/python -m unittest discover -s tests -v
"""

import asyncio
import json
import os
import unittest

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ['LLM_GATEWAY_MODE'] = 'proxy'

import httpx  # noqa: E402

from app import database, gateway_settings  # noqa: E402
from app.config import Settings  # noqa: E402
from app.litellm_admin import LiteLLMAdminClient, LiteLLMAdminError, redact, route_allowed  # noqa: E402
from app.model_catalog import ModelCatalog  # noqa: E402


class SettingsTests(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        gateway_settings.ensure_table()
        with database.SessionLocal() as session:
            session.query(gateway_settings.GatewaySetting).delete()
            session.query(database.PolicyAuditEvent).delete()
            session.commit()
        gateway_settings.invalidate_cache()

    def test_defaults_come_from_environment(self):
        self.assertEqual(gateway_settings.effective_default_model(), Settings.LLM_DEFAULT_MODEL)
        self.assertEqual(gateway_settings.effective_judge_model(), Settings.LLM_JUDGE_MODEL)
        self.assertEqual(gateway_settings.disabled_providers(), [])

    def test_override_persists_normalises_and_audits(self):
        result = gateway_settings.set_value('chat.judge_model', '  judge-fast ', 'ops@example.com')
        self.assertEqual(result['value'], 'judge-fast')
        self.assertEqual(gateway_settings.effective_judge_model(), 'judge-fast')
        gateway_settings.set_value('providers.disabled', ['openai', ' groq', 'groq'], 'ops@example.com')
        self.assertEqual(gateway_settings.disabled_providers(), ['groq', 'openai'])
        gateway_settings.set_value('chat.judge_model', None, 'ops@example.com')
        self.assertEqual(gateway_settings.effective_judge_model(), Settings.LLM_JUDGE_MODEL)
        with database.SessionLocal() as session:
            rows = session.query(database.PolicyAuditEvent).filter_by(action='setting_changed').all()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].actor, 'ops@example.com')

    def test_rejects_unknown_keys_and_wrong_types(self):
        with self.assertRaises(ValueError):
            gateway_settings.set_value('nope', 1, 'x')
        with self.assertRaises(ValueError):
            gateway_settings.set_value('providers.disabled', 'groq', 'x')


class AllowlistTests(unittest.TestCase):
    def test_management_routes_allowed(self):
        for method, path in [('GET', '/model/info'), ('POST', '/model/new'), ('POST', '/key/generate'), ('GET', '/key/list'),
                             ('POST', '/team/new'), ('GET', '/v1/mcp/server'), ('DELETE', '/v1/mcp/server/abc'),
                             ('GET', '/guardrails/list'), ('POST', '/guardrails'), ('POST', '/config/update'),
                             ('GET', '/global/spend/models'), ('GET', '/credentials'), ('DELETE', '/credentials/groq-default'),
                             ('GET', '/public/litellm_model_cost_map'), ('GET', '/cache/settings')]:
            self.assertTrue(route_allowed(method, path), f'{method} {path}')

    def test_inference_and_unknown_routes_denied(self):
        for method, path in [('POST', '/chat/completions'), ('POST', '/v1/chat/completions'), ('POST', '/embeddings'),
                             ('GET', '/key/info/../../chat/completions'), ('POST', '/mcp/'), ('GET', '/sso/key/generate'),
                             ('DELETE', '/model/info'), ('POST', '/credentials/migrate-encryption')]:
            self.assertFalse(route_allowed(method, path), f'{method} {path}')

    def test_redaction_hides_secret_like_fields(self):
        body = {'credential_name': 'anthropic-default', 'credential_values': {'api_key': 'sk-abc'},
                'models': ['a'], 'auth_value': 'tok', 'nested': {'client_secret': 'x', 'ok': 'y'}}
        out = redact(body)
        self.assertEqual(out['credential_values'], '***')
        self.assertEqual(out['auth_value'], '***')
        self.assertEqual(out['nested']['client_secret'], '***')
        self.assertEqual(out['nested']['ok'], 'y')
        self.assertEqual(out['credential_name'], 'anthropic-default')


def _proxy(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    _proxy.calls.append((request.method, path))
    if path == '/credentials' and request.method == 'GET':
        return httpx.Response(200, json={'success': True, 'credentials': [
            {'credential_name': 'anthropic-default', 'credential_info': {'custom_llm_provider': 'anthropic', 'created_by': 'ops'}}]})
    if path == '/credentials' and request.method == 'POST':
        return httpx.Response(200, json={'message': 'stored'})
    if path.startswith('/credentials/') and request.method == 'DELETE':
        return httpx.Response(200, json={'message': 'deleted'})
    if path == '/model/info':
        return httpx.Response(200, json={'data': [
            {'model_name': 'openai/gpt-oss-120b', 'litellm_params': {'model': 'groq/openai/gpt-oss-120b'}, 'model_info': {'id': 'g', 'litellm_provider': 'groq', 'mode': 'chat'}},
            {'model_name': 'nova-micro', 'litellm_params': {'model': 'bedrock/apac.amazon.nova-micro-v1:0'}, 'model_info': {'id': 'n', 'db_model': True, 'litellm_provider': 'bedrock_converse', 'mode': 'chat'}},
        ]})
    if path == '/model/new':
        _proxy.last_new = json.loads(request.content); return httpx.Response(200, json={'model_id': 'x'})
    if path == '/key/generate':
        return httpx.Response(200, json={'key': 'sk-generated', 'key_alias': json.loads(request.content).get('key_alias')})
    if path == '/health/readiness':
        return httpx.Response(200, json={'status': 'healthy', 'db': 'connected'})
    return httpx.Response(200, json={'data': []})
_proxy.calls = []


class ProviderEnablementTests(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        gateway_settings.ensure_table()
        with database.SessionLocal() as session:
            session.query(gateway_settings.GatewaySetting).delete(); session.commit()
        gateway_settings.invalidate_cache()
        self._saved = (Settings.LLM_PROVIDERS_ENABLED, Settings.LITELLM_PROXY_URL, Settings.LITELLM_API_KEY, Settings.LITELLM_ADMIN_API_KEY)
        Settings.LLM_PROVIDERS_ENABLED = ['groq']
        Settings.LITELLM_PROXY_URL = 'http://litellm.test'; Settings.LITELLM_API_KEY = 'sk-gw'; Settings.LITELLM_ADMIN_API_KEY = 'sk-admin'
        self.catalog = ModelCatalog(); self.catalog._client = httpx.AsyncClient(transport=httpx.MockTransport(_proxy))
        self.admin = LiteLLMAdminClient(); self.admin._client = httpx.AsyncClient(transport=httpx.MockTransport(_proxy))
        _proxy.calls.clear()

    def tearDown(self):
        (Settings.LLM_PROVIDERS_ENABLED, Settings.LITELLM_PROXY_URL, Settings.LITELLM_API_KEY, Settings.LITELLM_ADMIN_API_KEY) = self._saved

    def test_sources_env_litellm_iam_and_admin_disable(self):
        creds = asyncio.run(self.catalog.litellm_credentials())
        rows = {r['id']: r for r in self.catalog.providers(None, creds)}
        self.assertEqual(rows['groq']['credential_sources'], ['env']); self.assertTrue(rows['groq']['enabled'])
        self.assertEqual(rows['anthropic']['credential_sources'], ['litellm']); self.assertTrue(rows['anthropic']['enabled'])
        self.assertEqual(rows['bedrock']['credential_sources'], ['iam']); self.assertTrue(rows['bedrock']['enabled'])
        self.assertFalse(rows['openai']['has_credential']); self.assertFalse(rows['openai']['enabled'])
        gateway_settings.set_value('providers.disabled', ['anthropic'], 'ops')
        rows = {r['id']: r for r in self.catalog.providers(None, creds)}
        self.assertFalse(rows['anthropic']['enabled']); self.assertTrue(rows['anthropic']['disabled_by_admin'])

    def test_add_model_uses_stored_litellm_credential(self):
        asyncio.run(self.catalog.add_model('anthropic', 'claude-3-5-haiku-20241022', 'haiku', 'ops'))
        params = _proxy.last_new['litellm_params']
        self.assertEqual(params['litellm_credential_name'], 'anthropic-default')
        self.assertNotIn('api_key', params)

    def test_chat_rejection_for_disabled_model_and_provider(self):
        self.assertIsNone(asyncio.run(self.catalog.chat_model_rejection('nova-micro')))
        gateway_settings.set_value('models.disabled', ['nova-micro'], 'ops')
        self.assertIn('disabled by an administrator', asyncio.run(self.catalog.chat_model_rejection('nova-micro')))
        gateway_settings.set_value('models.disabled', [], 'ops')
        gateway_settings.set_value('providers.disabled', ['bedrock'], 'ops')
        self.assertIn("Provider 'bedrock'", asyncio.run(self.catalog.chat_model_rejection('nova-micro')))
        self.assertIsNone(asyncio.run(self.catalog.chat_model_rejection('openai/gpt-oss-120b')))

    def test_admin_client_uses_admin_key_and_audits_writes(self):
        status, payload = asyncio.run(self.admin.request('POST', '/key/generate', body={'key_alias': 'team-a', 'max_budget': 5}, actor='ops'))
        self.assertEqual((status, payload['key']), (200, 'sk-generated'))
        with self.assertRaises(LiteLLMAdminError) as ctx:
            asyncio.run(self.admin.request('POST', '/chat/completions', body={}, actor='ops'))
        self.assertEqual(ctx.exception.status_code, 403)
        asyncio.run(self.admin.store_provider_credential('openai', 'sk-live-secret', 'ops'))
        with database.SessionLocal() as session:
            rows = session.query(database.PolicyAuditEvent).filter(database.PolicyAuditEvent.action.like('litellm_%')).all()
        self.assertTrue(rows)
        joined = ' '.join(r.details for r in rows)
        self.assertNotIn('sk-live-secret', joined)
        self.assertIn('***', joined)


if __name__ == '__main__':
    unittest.main()
