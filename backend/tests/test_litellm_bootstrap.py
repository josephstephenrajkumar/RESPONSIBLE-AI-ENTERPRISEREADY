"""Unit tests for the LiteLLM runtime-settings bootstrap."""

import asyncio
import json
import os
import unittest

os.environ.setdefault('DATABASE_URL', 'sqlite://')

import httpx  # noqa: E402

from app import database, litellm_bootstrap  # noqa: E402
from app.config import Settings  # noqa: E402
from app.litellm_admin import litellm_admin, route_allowed  # noqa: E402


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        self._saved = (Settings.LITELLM_PROXY_URL, Settings.LITELLM_API_KEY, Settings.LITELLM_ADMIN_API_KEY)
        Settings.LITELLM_PROXY_URL = 'http://litellm.test'; Settings.LITELLM_API_KEY = 'sk-gw'; Settings.LITELLM_ADMIN_API_KEY = 'sk-admin'
        self.calls = []
        self.router = {'num_retries': 2, 'cooldown_time': 5, 'fallbacks': None}

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append((request.method, request.url.path))
            if request.url.path == '/get/config/callbacks':
                return httpx.Response(200, json={'callbacks': [{'name': 'otel'}], 'router_settings': self.router, 'available_callbacks': {}})
            if request.url.path == '/key/info':
                return httpx.Response(200, json={'info': {'key_alias': 'app-a', 'team_id': 't1', 'max_budget': 5.0, 'models': ['m1'], 'rpm_limit': None}})
            if request.url.path == '/key/delete':
                return httpx.Response(200, json={'deleted_keys': json.loads(request.content)['keys']})
            if request.url.path == '/key/generate':
                body = json.loads(request.content); self.generated = body
                return httpx.Response(200, json={'key': 'sk-new', 'key_alias': body.get('key_alias')})
            if request.url.path == '/config/update':
                body = json.loads(request.content); self.router = {**self.router, **body.get('router_settings', {})}
                return httpx.Response(200, json={'message': 'Config updated successfully'})
            return httpx.Response(200, json={})
        litellm_admin._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def tearDown(self):
        (Settings.LITELLM_PROXY_URL, Settings.LITELLM_API_KEY, Settings.LITELLM_ADMIN_API_KEY) = self._saved
        litellm_admin._client = None

    def test_defaults_file_is_valid_and_has_router_settings(self):
        defaults = litellm_bootstrap.load_defaults()
        self.assertIn('router_settings', defaults)
        self.assertIn('fallbacks', defaults['router_settings'])
        self.assertNotIn('_comment', defaults)

    def test_seeds_once_then_idempotent(self):
        first = asyncio.run(litellm_bootstrap.ensure_runtime_defaults('tester'))
        self.assertTrue(first['applied'])
        self.assertIn(('POST', '/config/update'), self.calls)
        second = asyncio.run(litellm_bootstrap.ensure_runtime_defaults('tester'))
        self.assertFalse(second['applied']); self.assertIn('already present', second['reason'])
        forced = asyncio.run(litellm_bootstrap.ensure_runtime_defaults('tester', force=True))
        self.assertTrue(forced['applied'])
        with database.SessionLocal() as session:
            actions = [r.action for r in session.query(database.PolicyAuditEvent).all()]
        self.assertIn('litellm_runtime_defaults_seeded', actions)

    def test_current_config_shape(self):
        cfg = asyncio.run(litellm_bootstrap.current_config())
        for key in ('defaults', 'router_settings', 'callbacks', 'available_callbacks', 'cache', 'general_settings_fields', 'pinned_in_config_yaml'):
            self.assertIn(key, cfg)

    def test_key_rotation_carries_scope_and_deletes_old(self):
        created = asyncio.run(litellm_admin.rotate_key('sk-old-token-123', 'tester'))
        self.assertEqual(created['key'], 'sk-new')
        self.assertEqual(self.generated['key_alias'], 'app-a'); self.assertEqual(self.generated['team_id'], 't1')
        self.assertEqual(self.generated['max_budget'], 5.0); self.assertEqual(self.generated['models'], ['m1'])
        self.assertNotIn('rpm_limit', self.generated)
        paths = [p for _, p in self.calls]
        self.assertLess(paths.index('/key/delete'), paths.index('/key/generate'))
        with database.SessionLocal() as session:
            self.assertTrue(any(r.action == 'litellm_key_rotated' for r in session.query(database.PolicyAuditEvent).all()))

    def test_cache_flush_allowed_inference_not(self):
        self.assertTrue(route_allowed('POST', '/cache/flushall'))
        self.assertTrue(route_allowed('POST', '/config/field/update'))
        self.assertFalse(route_allowed('POST', '/chat/completions'))


if __name__ == '__main__':
    unittest.main()
