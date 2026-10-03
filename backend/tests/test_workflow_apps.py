"""Unit tests for the Workflow Apps control plane (Activepieces integration).
Run from backend/:
    ./venv/bin/python -m unittest tests.test_workflow_apps -v
Everything external (Activepieces, LiteLLM) is replaced by fakes; the database is in-memory SQLite.
"""

import asyncio
import json
import os
import unittest
from unittest import mock

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ['LLM_GATEWAY_MODE'] = 'proxy'
os.environ['ACTIVEPIECES_SERVICE_PASSWORD'] = 'unit-test-password'  # secret-scan:allow unit-test placeholder

from fastapi import HTTPException  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402

from app import auth, database, workflow_apps, workflow_templates, workflow_tokens  # noqa: E402
from app.activepieces_client import ActivepiecesError  # noqa: E402


def run(coro):
    # A fresh loop per call: other test modules close the default loop, and the fakes hold no loop state.
    return asyncio.run(coro)


class FakeActivepieces:
    """Minimal stand-in for ActivepiecesClient recording every call."""

    def __init__(self, pieces=None, fail_import=False):
        self.project_id = 'proj_1'
        self.signed_in = True
        self.pieces = pieces or {
            workflow_templates.FORMS_PIECE: {'version': '0.5.0'},
            workflow_templates.GATEWAY_PIECE: {'version': '0.1.0'},
            workflow_templates.LITELLM_PIECE: {'version': '0.1.0'},
        }
        self.calls = []
        self.fail_import = fail_import
        self.flows = {}

    async def ping(self):
        return True

    async def sign_in(self):
        return {'projectId': self.project_id}

    async def get_piece(self, name):
        return self.pieces.get(name)

    async def upsert_custom_auth_connection(self, external_id, display_name, piece_name, props):
        self.calls.append(('connection', external_id, piece_name, props))
        return {'id': f'conn_{external_id}'}

    async def delete_connection(self, connection_id):
        self.calls.append(('delete_connection', connection_id))

    async def create_flow(self, display_name, external_id, metadata=None):
        self.calls.append(('create_flow', display_name, external_id))
        self.flows[external_id] = {'id': f'flow_{external_id}', 'status': 'DISABLED'}
        return self.flows[external_id]

    async def import_flow(self, flow_id, display_name, trigger):
        if self.fail_import:
            raise ActivepiecesError(400, 'bad template')
        self.calls.append(('import_flow', flow_id, trigger))
        return {'id': flow_id, 'version': {'valid': True}}

    async def publish_flow(self, flow_id):
        self.calls.append(('publish', flow_id))
        return {'id': flow_id, 'status': 'ENABLED', 'publishedVersionId': 'v1'}

    async def set_flow_status(self, flow_id, enabled):
        self.calls.append(('status', flow_id, enabled))
        return {'id': flow_id, 'status': 'ENABLED' if enabled else 'DISABLED'}

    async def delete_flow(self, flow_id):
        self.calls.append(('delete_flow', flow_id))

    async def list_runs(self, flow_id, limit=20):
        return [{'id': 'run_1', 'status': 'SUCCEEDED', 'created': '2026-10-03T00:00:00Z'}]

    async def chat(self, flow_id, chat_id, message):
        self.calls.append(('chat', flow_id, chat_id, message))
        return 200, {'type': 'markdown', 'value': f'echo: {message}'}


class FakeActivepiecesBootstrap(FakeActivepieces):
    def __init__(self, configs=None):
        super().__init__(pieces={workflow_templates.FORMS_PIECE: {'version': '0.5.0'}})
        self.configs = configs or []
        self.installed = []
        self.providers = []

    async def install_piece_archive(self, path, name, version):
        self.installed.append((name, version))
        self.pieces[name] = {'version': version}
        return {'name': name, 'version': version}

    async def list_ai_provider_configs(self):
        return self.configs

    async def create_ai_provider(self, body):
        self.providers.append(('create', body))
        return {'id': 'prov_new'}

    async def update_ai_provider(self, provider_id, body):
        self.providers.append(('update', provider_id, body))
        return {'id': provider_id}

    async def delete_ai_provider(self, provider_id):
        self.providers.append(('delete', provider_id))
        self.configs = [c for c in self.configs if c.get('id') != provider_id]


class FakeLiteLLM:
    def __init__(self, spend_rows=None):
        self.calls = []
        self.spend_rows = spend_rows or []

    async def post(self, path, body, actor):
        self.calls.append(('POST', path, body))
        if path == '/key/generate':
            return {'key': 'sk-unit-test-virtual-key-000000', 'token': 'hash-' + body['key_alias']}  # secret-scan:allow fake key for unit test
        return {}

    async def get(self, path, **params):
        self.calls.append(('GET', path, params))
        return self.spend_rows


def admin_user(tenant='t1'):
    return auth.AuthenticatedUser(user_id='u1', email='admin@example.com', username='admin', tenant_id=tenant, groups=('admin',), claims={})


class WorkflowBase(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.create_all(bind=database.engine)
        workflow_apps.ensure_tables()
        with database.SessionLocal() as session:
            session.query(workflow_apps.WorkflowApp).delete()
            session.query(workflow_apps.WorkflowSetting).delete()
            session.query(workflow_tokens.WorkflowAppToken).delete()
            session.query(database.LLMUsageEventRecord).delete()
            session.commit()
        self.ap = FakeActivepieces()
        self.llm = FakeLiteLLM()
        self._patches = [mock.patch.object(workflow_apps, 'activepieces', self.ap), mock.patch.object(workflow_apps, 'litellm_admin', self.llm)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()


class TokenTests(WorkflowBase):
    def test_issue_authenticate_revoke(self):
        token = workflow_tokens.issue_token('wf_1', 'tenant-a')
        self.assertTrue(token.startswith('rai_app_'))
        self.assertEqual(workflow_tokens.authenticate_app_token(token), {'app_id': 'wf_1', 'tenant_id': 'tenant-a'})
        self.assertIsNone(workflow_tokens.authenticate_app_token('rai_app_nope'))
        self.assertIsNone(workflow_tokens.authenticate_app_token('sk-not-an-app-token'))
        self.assertEqual(workflow_tokens.revoke_tokens('wf_1'), 1)
        self.assertIsNone(workflow_tokens.authenticate_app_token(token))

    def test_get_current_user_accepts_app_token_and_denies_admin_routes(self):
        token = workflow_tokens.issue_token('wf_2', 'tenant-b')
        creds = HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)
        user = run(auth.get_current_user(credentials=creds, x_tenant_id=None))
        self.assertEqual(user.user_id, 'workflow-app:wf_2')
        self.assertEqual(user.tenant_id, 'tenant-b')
        self.assertEqual(user.client_id, 'workflow-app:wf_2')
        self.assertFalse(auth.user_can_manage_workflows(user))
        self.assertFalse(auth.user_can_manage_models(user))
        with self.assertRaises(HTTPException) as ctx:
            run(auth.get_current_user(credentials=HTTPAuthorizationCredentials(scheme='Bearer', credentials='rai_app_invalid'), x_tenant_id=None))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_workflow_permission_groups(self):
        for group, expected in (('admin', True), ('workflow-admin', True), ('model-admin', True), ('finops', False), ('workflow-app', False)):
            user = auth.AuthenticatedUser(user_id='x', email='', groups=(group,))
            self.assertEqual(auth.user_can_manage_workflows(user), expected, group)


class TemplateTests(unittest.TestCase):
    versions = {workflow_templates.FORMS_PIECE: '0.5.0', workflow_templates.GATEWAY_PIECE: '0.1.0', workflow_templates.LITELLM_PIECE: '0.1.0'}

    def build(self, template):
        return workflow_templates.build_trigger(template, versions=self.versions, connection_gateway='wf_9-gateway', connection_litellm='wf_9-litellm', app_id='wf_9', bot_name='Bot', rai_mode='framework', model='chat-default')

    def test_responsible_ai_chat_template_wires_gateway_piece(self):
        trigger = self.build('responsible-ai-chat')
        self.assertEqual(trigger['settings']['triggerName'], 'chat_submission')
        self.assertEqual(trigger['settings']['pieceVersion'], '~0.5.0')
        step = trigger['nextAction']
        self.assertEqual(step['settings']['pieceName'], workflow_templates.GATEWAY_PIECE)
        self.assertEqual(step['settings']['actionName'], 'chat')
        self.assertEqual(step['settings']['input']['auth'], "{{connections['wf_9-gateway']}}")
        self.assertEqual(step['settings']['input']['mode'], 'framework')
        self.assertEqual(step['settings']['input']['agentId'], 'workflow-app:wf_9')
        self.assertEqual(step['nextAction']['settings']['actionName'], 'return_response')
        self.assertIn("{{step_1['answer']}}", step['nextAction']['settings']['input']['markdown'])
        for key in step['settings']['input']:
            self.assertIn(key, step['settings']['propertySettings'])

    def test_litellm_template_uses_app_key_and_tags(self):
        trigger = self.build('litellm-chat')
        step = trigger['nextAction']
        self.assertEqual(step['settings']['pieceName'], workflow_templates.LITELLM_PIECE)
        self.assertEqual(step['settings']['input']['auth'], "{{connections['wf_9-litellm']}}")
        self.assertEqual(step['settings']['input']['appId'], 'wf_9')
        self.assertEqual(step['settings']['input']['model'], 'chat-default')

    def test_blank_template_is_trigger_only(self):
        self.assertNotIn('nextAction', self.build('blank'))

    def test_unknown_template(self):
        with self.assertRaises(ValueError):
            self.build('nope')


class AppLifecycleTests(WorkflowBase):
    def test_create_publish_chat_delete(self):
        payload = workflow_apps.WorkflowAppCreate(name='Support bot', template='responsible-ai-chat', monthly_budget_usd=5)
        created = run(workflow_apps.create_app(payload, admin_user()))
        self.assertTrue(created['id'].startswith('wf_'))
        self.assertEqual(created['status'], 'draft')
        self.assertEqual(created['client_id'], f"workflow-app:{created['id']}")
        self.assertNotIn('builder_url', created)  # the engine has no user-facing URL; the Studio is the builder
        # LiteLLM key with budget and attribution tags; only the hash is stored
        key_call = next(c for c in self.llm.calls if c[1] == '/key/generate')
        self.assertEqual(key_call[2]['max_budget'], 5)
        self.assertIn(f"client_id:workflow-app:{created['id']}", key_call[2]['metadata']['tags'])
        with database.SessionLocal() as session:
            row = session.get(workflow_apps.WorkflowApp, created['id'])
            self.assertEqual(row.litellm_key_hash, 'hash-wfapp-' + created['id'])
            self.assertNotIn('sk-', row.litellm_key_hash)
        # Two encrypted connections carry the plaintext credentials to the engine
        conns = [c for c in self.ap.calls if c[0] == 'connection']
        self.assertEqual([c[2] for c in conns], [workflow_templates.GATEWAY_PIECE, workflow_templates.LITELLM_PIECE])
        self.assertTrue(conns[0][3]['appToken'].startswith('rai_app_'))
        self.assertEqual(conns[1][3]['apiKey'], 'sk-unit-test-virtual-key-000000')  # secret-scan:allow fake key for unit test
        # the app token authenticates against the gateway
        self.assertEqual(workflow_tokens.authenticate_app_token(conns[0][3]['appToken'])['app_id'], created['id'])
        # flow imported from the template
        imported = next(c for c in self.ap.calls if c[0] == 'import_flow')
        self.assertEqual(imported[2]['nextAction']['settings']['pieceName'], workflow_templates.GATEWAY_PIECE)

        # publish, chat through the gateway, disable, delete
        published = run(workflow_apps.publish_app(created['id'], admin_user()))
        self.assertEqual(published['status'], 'published')
        reply = run(workflow_apps.app_chat(created['id'], workflow_apps.WorkflowChatRequest(message='hello'), admin_user()))
        self.assertEqual(reply['answer'], 'echo: hello')
        disabled = run(workflow_apps.set_app_status(created['id'], workflow_apps.WorkflowAppStatusUpdate(enabled=False), admin_user()))
        self.assertEqual(disabled['status'], 'disabled')
        with self.assertRaises(HTTPException) as ctx:
            run(workflow_apps.app_chat(created['id'], workflow_apps.WorkflowChatRequest(message='hello'), admin_user()))
        self.assertEqual(ctx.exception.status_code, 409)
        run(workflow_apps.delete_app_route(created['id'], admin_user()))
        self.assertIn(('delete_flow', f"flow_{created['id']}"), self.ap.calls)
        self.assertTrue(any(c[1] == '/key/delete' for c in self.llm.calls))
        self.assertIsNone(workflow_tokens.authenticate_app_token(conns[0][3]['appToken']))

    def test_tenant_isolation(self):
        created = run(workflow_apps.create_app(workflow_apps.WorkflowAppCreate(name='A'), admin_user('t1')))
        self.assertEqual(len(workflow_apps.list_apps(admin_user('t1'))['apps']), 1)
        self.assertEqual(len(workflow_apps.list_apps(admin_user('t2'))['apps']), 0)
        with self.assertRaises(HTTPException) as ctx:
            workflow_apps.get_app(created['id'], admin_user('t2'))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_failed_import_rolls_back_key_token_and_flow(self):
        self.ap.fail_import = True
        with self.assertRaises(HTTPException) as ctx:
            run(workflow_apps.create_app(workflow_apps.WorkflowAppCreate(name='Broken'), admin_user()))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertTrue(any(c[1] == '/key/delete' for c in self.llm.calls))
        self.assertTrue(any(c[0] == 'delete_flow' for c in self.ap.calls))
        self.assertEqual(len(workflow_apps.list_apps(admin_user())['apps']), 0)
        with database.SessionLocal() as session:
            self.assertEqual(session.query(workflow_tokens.WorkflowAppToken).filter_by(revoked_at=None).count(), 0)

    def test_missing_pieces_block_creation(self):
        self.ap.pieces.pop(workflow_templates.GATEWAY_PIECE)
        with self.assertRaises(HTTPException) as ctx:
            run(workflow_apps.create_app(workflow_apps.WorkflowAppCreate(name='X'), admin_user()))
        self.assertEqual(ctx.exception.status_code, 503)


class UsageSyncTests(WorkflowBase):
    def test_spend_rows_become_usage_events_once(self):
        created = run(workflow_apps.create_app(workflow_apps.WorkflowAppCreate(name='Metered'), admin_user()))
        self.llm.spend_rows = [
            {'request_id': 'req-1', 'model': 'groq/openai/gpt-oss-120b', 'spend': 0.0012, 'prompt_tokens': 10, 'completion_tokens': 20, 'total_tokens': 30,
             'startTime': '2026-10-03T01:00:00Z', 'endTime': '2026-10-03T01:00:01.500Z', 'api_base': 'https://api.groq.com', 'user': 'session-1'},
            {'request_id': 'req-2', 'model': 'chat-default', 'spend': 0.0005, 'total_tokens': 12, 'startTime': '2026-10-03T01:01:00Z', 'endTime': '2026-10-03T01:01:00.200Z'},
        ]
        first = run(workflow_apps.usage_sync('test'))
        self.assertEqual(first['inserted'], 2)
        second = run(workflow_apps.usage_sync('test'))
        self.assertEqual(second['inserted'], 0)
        self.assertEqual(second['rows_seen'], 2)
        summary = database.get_finops_summary(days=7, monthly_budget_usd=0)
        key = f"workflow-app:{created['id']}"
        # the app shows up in the FinOps client breakdown with the proxy-reported spend
        self.assertIn(key, json.dumps(summary))
        self.assertAlmostEqual(float(summary['totals']['cost_usd']) if 'totals' in summary else 0.0017, 0.0017, places=4)
        with database.SessionLocal() as session:
            rows = session.query(database.LLMUsageEventRecord).filter_by(purpose='workflow').order_by(database.LLMUsageEventRecord.call_id).all()
            self.assertEqual([r.call_id for r in rows], ['req-1', 'req-2'])
            self.assertEqual(rows[0].latency_ms, 1500)
            self.assertEqual(rows[0].provider, 'groq')
            self.assertEqual(rows[0].gateway_mode, 'proxy-direct')
            self.assertEqual(rows[0].cost_source, 'litellm')
            self.assertEqual(rows[0].client_id, key)


if __name__ == '__main__':
    unittest.main()


class BootstrapTests(WorkflowBase):
    def _run_bootstrap(self, ap, archives, force=False):
        with mock.patch.object(workflow_apps, 'activepieces', ap), mock.patch.object(workflow_apps, 'piece_archives', lambda: archives):
            return run(workflow_apps.bootstrap('test', force=force))

    def test_fresh_engine_installs_pieces_and_creates_provider_with_scoped_key(self):
        ap = FakeActivepiecesBootstrap()
        archives = [{'name': workflow_templates.GATEWAY_PIECE, 'version': '0.1.1', 'path': '/nope.tgz'},
                    {'name': workflow_templates.LITELLM_PIECE, 'version': '0.1.1', 'path': '/nope.tgz'}]
        result = self._run_bootstrap(ap, archives)
        self.assertEqual(result['errors'], [])
        self.assertEqual(sorted(ap.installed), sorted([(workflow_templates.GATEWAY_PIECE, '0.1.1'), (workflow_templates.LITELLM_PIECE, '0.1.1')]))
        self.assertEqual(result['ai_provider']['state'], 'created')
        kind, body = ap.providers[0]
        self.assertEqual(kind, 'create')
        self.assertEqual(body['provider'], 'custom')
        self.assertEqual(body['config']['apiKeyHeader'], 'Authorization')
        self.assertTrue(body['auth']['apiKey'].startswith('Bearer sk-'))
        self.assertNotIn('master', body['auth']['apiKey'])
        self.assertTrue(any(m['modelType'] == 'text' for m in body['config']['models']))
        self.assertTrue(workflow_apps.setting_get('platform_key_hash'))
        self.assertEqual(workflow_apps.setting_get('ai_provider_id'), 'prov_new')

    def test_existing_provider_is_kept_unless_forced(self):
        ap = FakeActivepiecesBootstrap(configs=[{'id': 'prov_old', 'name': workflow_apps.AI_PROVIDER_NAME, 'provider': 'custom'}])
        ap.pieces[workflow_templates.GATEWAY_PIECE] = {'version': '0.1.1'}
        ap.pieces[workflow_templates.LITELLM_PIECE] = {'version': '0.1.1'}
        archives = [{'name': workflow_templates.GATEWAY_PIECE, 'version': '0.1.1', 'path': '/nope.tgz'}]
        result = self._run_bootstrap(ap, archives)
        self.assertEqual(result['errors'], [])
        self.assertEqual(ap.installed, [])
        self.assertEqual(result['ai_provider']['state'], 'present')
        self.assertEqual(ap.providers, [])
        forced = self._run_bootstrap(ap, archives, force=True)
        self.assertEqual(forced['ai_provider']['state'], 'updated')
        self.assertEqual(ap.providers[0][0], 'update')
        self.assertEqual(ap.providers[0][1], 'prov_old')

    def test_unreachable_engine_reports_without_raising(self):
        ap = FakeActivepiecesBootstrap()
        async def down():
            return False
        ap.ping = down
        result = self._run_bootstrap(ap, [])
        self.assertFalse(result['engine_reachable'])
        self.assertTrue(result['errors'])

    def test_forced_bootstrap_uses_stored_provider_id_when_listing_misses_it(self):
        ap = FakeActivepiecesBootstrap(configs=[])
        ap.pieces[workflow_templates.GATEWAY_PIECE] = {'version': '0.1.1'}
        ap.pieces[workflow_templates.LITELLM_PIECE] = {'version': '0.1.1'}
        workflow_apps.setting_set('ai_provider_id', 'prov_from_other_worker')
        forced = self._run_bootstrap(ap, [], force=True)
        self.assertEqual(forced['errors'], [])
        self.assertEqual(forced['ai_provider']['state'], 'updated')
        self.assertEqual(ap.providers[0][:2], ('update', 'prov_from_other_worker'))

    def test_duplicate_name_on_create_is_adopted(self):
        class LateListing(FakeActivepiecesBootstrap):
            async def create_ai_provider(self, body):
                self.configs = [{'id': 'prov_race', 'name': workflow_apps.AI_PROVIDER_NAME, 'provider': 'custom'}]
                raise ActivepiecesError(409, {'code': 'VALIDATION', 'params': {'message': 'Another key of this provider already uses this name'}})
        ap = LateListing()
        ap.pieces[workflow_templates.GATEWAY_PIECE] = {'version': '0.1.1'}
        ap.pieces[workflow_templates.LITELLM_PIECE] = {'version': '0.1.1'}
        result = self._run_bootstrap(ap, [])
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['ai_provider']['state'], 'updated')
        self.assertEqual(ap.providers[0][:2], ('update', 'prov_race'))
        self.assertEqual(workflow_apps.setting_get('ai_provider_id'), 'prov_race')

    def test_duplicate_providers_are_removed_keeping_the_recorded_one(self):
        ap = FakeActivepiecesBootstrap(configs=[
            {'id': 'prov_a', 'name': workflow_apps.AI_PROVIDER_NAME, 'provider': 'custom'},
            {'id': 'prov_b', 'name': workflow_apps.AI_PROVIDER_NAME, 'provider': 'custom'},
            {'id': 'other', 'name': 'OpenAI direct', 'provider': 'openai'},
        ])
        ap.pieces[workflow_templates.GATEWAY_PIECE] = {'version': '0.1.1'}
        ap.pieces[workflow_templates.LITELLM_PIECE] = {'version': '0.1.1'}
        workflow_apps.setting_set('ai_provider_id', 'prov_b')
        result = self._run_bootstrap(ap, [], force=True)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['ai_provider_duplicates_removed'], ['prov_a'])
        self.assertIn(('delete', 'prov_a'), ap.providers)
        self.assertEqual([p for p in ap.providers if p[0] == 'update'][0][1], 'prov_b')
        self.assertEqual([c['id'] for c in ap.configs], ['prov_b', 'other'])

    def test_update_conflict_dedupes_then_retries(self):
        class ConflictOnce(FakeActivepiecesBootstrap):
            def __init__(self):
                super().__init__(configs=[{'id': 'prov_keep', 'name': workflow_apps.AI_PROVIDER_NAME, 'provider': 'custom'}])
                self.updates = 0
            async def update_ai_provider(self, provider_id, body):
                self.updates += 1
                if self.updates == 1:
                    # a duplicate appeared between listing and update
                    self.configs.append({'id': 'prov_dup', 'name': workflow_apps.AI_PROVIDER_NAME, 'provider': 'custom'})
                    raise ActivepiecesError(409, {'code': 'VALIDATION', 'params': {'message': 'Another key of this provider already uses this name'}})
                self.providers.append(('update', provider_id, body))
                return {'id': provider_id}
        ap = ConflictOnce()
        ap.pieces[workflow_templates.GATEWAY_PIECE] = {'version': '0.1.1'}
        ap.pieces[workflow_templates.LITELLM_PIECE] = {'version': '0.1.1'}
        result = self._run_bootstrap(ap, [], force=True)
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['ai_provider']['state'], 'updated')
        self.assertEqual(result['ai_provider_duplicates_removed'], ['prov_dup'])
        self.assertEqual(ap.updates, 2)

    def test_bootstrap_lock_is_exclusive_and_releasable(self):
        self.assertTrue(workflow_apps.acquire_bootstrap_lock('w1'))
        self.assertFalse(workflow_apps.acquire_bootstrap_lock('w2'))
        self.assertTrue(workflow_apps.acquire_bootstrap_lock('w1'))  # re-entrant for the owner
        workflow_apps.release_bootstrap_lock('w1')
        self.assertTrue(workflow_apps.acquire_bootstrap_lock('w2'))
        workflow_apps.release_bootstrap_lock('w2')

    def test_second_worker_skips_while_locked(self):
        ap = FakeActivepiecesBootstrap()
        self.assertTrue(workflow_apps.acquire_bootstrap_lock('other-worker'))
        result = self._run_bootstrap(ap, [])
        self.assertTrue(result.get('skipped'))
        self.assertEqual(result['errors'], [])
        self.assertIn('another gateway worker', result['note'])
        self.assertEqual(ap.installed, [])
        workflow_apps.release_bootstrap_lock('other-worker')
